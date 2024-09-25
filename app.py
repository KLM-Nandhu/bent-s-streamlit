import streamlit as st
import openai
from typing import List, Dict
import asyncio
import aiohttp
from io import BytesIO
from datetime import datetime
import base64
from googleapiclient.discovery import build
import re
import random
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Improved CSS for better UI
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
    
    body {
        font-family: 'Poppins', sans-serif;
        background-color: #f0f4f8;
        color: #333;
        line-height: 1.6;
    }
    .stApp {
        max-width: 1000px;
        margin: 0 auto;
    }
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1 {
        font-weight: 700;
        color: #2c3e50;
        text-align: center;
        margin-bottom: 2rem;
    }
    .stButton>button {
        background-color: #3498db;
        color: white;
        font-weight: 600;
        border-radius: 25px;
        padding: 0.5rem 2rem;
        font-size: 1.1em;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #2980b9;
        transform: translateY(-2px);
    }
    .blog-container {
        background-color: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-top: 2rem;
    }
    .blog-title {
        font-weight: 700;
        font-size: 2.5em;
        color: #2c3e50;
        text-align: center;
        margin-bottom: 1rem;
    }
    .blog-meta {
        text-align: center;
        color: #7f8c8d;
        margin-bottom: 1rem;
        font-size: 0.9em;
    }
    .blog-content img {
        max-width: 100%;
        height: auto;
        margin: 1rem auto;
        display: block;
        border-radius: 10px;
    }
    .blog-content h2 {
        font-weight: 600;
        color: #2c3e50;
        margin-top: 1.5rem;
    }
    .blog-content p {
        margin-bottom: 1rem;
        font-weight: 300;
    }
    .comment {
        background-color: #f8f9fa;
        border-left: 4px solid #3498db;
        padding: 1rem;
        margin-bottom: 1rem;
        border-radius: 5px;
    }
    .center-content {
        display: flex;
        justify-content: center;
        align-items: center;
        flex-direction: column;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=3600)
async def get_video_info(video_id: str) -> Dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}") as response:
            data = await response.json()
            video_data = data['items'][0]
            return {
                'id': video_id,
                'title': video_data['snippet']['title'],
                'description': video_data['snippet']['description'],
                'thumbnail_url': video_data['snippet']['thumbnails']['high']['url'],
                'view_count': video_data['statistics']['viewCount'],
                'like_count': video_data['statistics'].get('likeCount', 'N/A'),
                'duration': video_data['contentDetails']['duration'],
                'published_at': video_data['snippet']['publishedAt']
            }

@st.cache_data(ttl=3600)
async def get_all_comments(video_id: str) -> List[Dict]:
    async with aiohttp.ClientSession() as session:
        comments = []
        next_page_token = None
        while True:
            url = f"https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={video_id}&key={YOUTUBE_API_KEY}&maxResults=100"
            if next_page_token:
                url += f"&pageToken={next_page_token}"
            
            async with session.get(url) as response:
                data = await response.json()
                for item in data['items']:
                    comment = item['snippet']['topLevelComment']['snippet']
                    comments.append({
                        'author': comment['authorDisplayName'],
                        'text': comment['textDisplay'],
                        'likes': comment['likeCount'],
                        'published_at': comment['publishedAt']
                    })
                
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
        
        return comments

@st.cache_data(ttl=3600)
def get_video_transcript_with_timestamps(video_id: str) -> List[Dict]:
    methods = [
        fetch_transcript_directly,
        fetch_transcript_with_rotating_proxy,
        fetch_transcript_with_selenium,
        fetch_transcript_from_third_party,
        fetch_transcript_with_custom_headers
    ]
    
    random.shuffle(methods)  # Randomize the order of methods
    
    for method in methods:
        try:
            transcript = method(video_id)
            if transcript:
                return transcript
        except Exception as e:
            print(f"Method {method.__name__} failed: {str(e)}")
        time.sleep(random.uniform(1, 3))  # Add random delay between attempts
    
    return f"An error occurred while fetching the transcript: All methods failed"

def fetch_transcript_directly(video_id: str) -> List[Dict]:
    return YouTubeTranscriptApi.get_transcript(video_id)

def fetch_transcript_with_rotating_proxy(video_id: str) -> List[Dict]:
    proxy_api_url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
    response = requests.get(proxy_api_url)
    proxies = response.text.strip().split('\r\n')
    
    for proxy in proxies:
        try:
            proxy_dict = {
                'http': f'http://{proxy}',
                'https': f'http://{proxy}',
            }
            return YouTubeTranscriptApi.get_transcript(video_id, proxies=proxy_dict)
        except Exception as e:
            print(f"Proxy {proxy} failed: {str(e)}")
    
    raise Exception("All proxies failed")

def fetch_transcript_with_selenium(video_id: str) -> List[Dict]:
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(f"https://www.youtube.com/watch?v={video_id}")
        
        # Wait for and click the "Show Transcript" button
        transcript_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='Show transcript']"))
        )
        transcript_button.click()
        
        # Wait for the transcript to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[id='segments-container']"))
        )
        
        # Extract transcript
        transcript_elements = driver.find_elements(By.CSS_SELECTOR, "div[id='segments-container'] div.segment")
        transcript = []
        for element in transcript_elements:
            time_element = element.find_element(By.CSS_SELECTOR, "div.segment-timestamp")
            text_element = element.find_element(By.CSS_SELECTOR, "div.segment-text")
            transcript.append({
                "text": text_element.text,
                "start": time_element.text,
                "duration": 0  # We don't have duration information in this method
            })
        
        return transcript
    finally:
        driver.quit()

def fetch_transcript_from_third_party(video_id: str) -> List[Dict]:
    # This is a placeholder for a hypothetical third-party service
    api_url = f"https://api.transcriptservice.com/v1/youtube/{video_id}"
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Third-party API request failed with status code {response.status_code}")

def fetch_transcript_with_custom_headers(video_id: str) -> List[Dict]:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'TE': 'Trailers',
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        return YouTubeTranscriptApi.get_transcript(video_id, proxies=session.proxies, headers=session.headers)
    except Exception as e:
        raise Exception(f"Custom headers method failed: {str(e)}")

def format_time(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

async def process_transcript_chunk(chunk: str, video_id: str) -> str:
    prompt = f"""This is a portion of a video transcript. Please organize this content into the following structure:

For each distinct topic or section, include:
Product name (if applicable):
Starting timestamp:
Ending Timestamp:
Transcript:

The goal is to not summarize or alter any information, but just reorganize the existing transcript into this structure. Use the provided timestamps to determine the start and end times for each section.

Here's the transcript chunk:
{chunk}

Please format the response as follows:

[Organized content here]
"""

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that organizes video transcripts without altering their content."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while processing with GPT-3.5: {str(e)}"

async def process_full_transcript(transcript: List[Dict], video_id: str) -> str:
    chunk_size = 10000  # Adjust this value based on your needs
    full_transcript = " ".join([f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript])
    chunks = [full_transcript[i:i+chunk_size] for i in range(0, len(full_transcript), chunk_size)]
    
    tasks = [process_transcript_chunk(chunk, video_id) for chunk in chunks]
    processed_chunks = await asyncio.gather(*tasks)
    
    return "\n\n".join(processed_chunks)

async def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    prompt = f"""Create a concise blog post based on the following YouTube video transcript and information:

Title: {video_info['title']}
Description: {video_info['description']}

Transcript: {processed_transcript[:2000]}...

Include:
1. Brief introduction
2. 3-5 key points
3. Short conclusion

Format the blog post in HTML, using appropriate tags for headings and paragraphs.
"""

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a skilled content writer who creates engaging and informative blog posts from YouTube video transcripts."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while generating the blog post: {str(e)}"

def get_image_html(img_url: str, alt_text: str) -> str:
    return f'<img src="{img_url}" alt="{alt_text}" class="blog-image"/>'

def make_links_clickable(text: str) -> str:
    return re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank">\1</a>', text)

def format_blog_post(blog_post: str, video_info: Dict) -> str:
    formatted_post = f"""
    <div class='blog-container'>
        <h1 class='blog-title'>{video_info['title']}</h1>
        <div class='blog-meta'>Published on {video_info['published_at']} | {video_info['view_count']} views | {video_info['like_count']} likes</div>
        <div class='center-content'>
            <img src="{video_info['thumbnail_url']}" alt="{video_info['title']}" class="blog-image" style="max-width: 100%; height: auto;"/>
        </div>
        <div class='blog-content'>
            {blog_post}
        </div>
    </div>
    """
    return formatted_post

async def main():
    st.title("BENT-S-BLOG")

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        video_id = st.text_input("Enter YouTube Video ID")
        process_button = st.button("Generate")

    if process_button and video_id:
        with st.spinner("Generating blog post, please wait..."):
            start_time = time.time()
            
            try:
                # Concurrent fetching of video info, transcript, and comments
                video_info_task = asyncio.create_task(get_video_info(video_id))
                transcript_task = asyncio.create_task(asyncio.to_thread(get_video_transcript_with_timestamps, video_id))
                comments_task = asyncio.create_task(get_all_comments(video_id))
                
                video_info, transcript, comments = await asyncio.gather(video_info_task, transcript_task, comments_task)
                
                if isinstance(video_info, dict) and isinstance(transcript, list) and isinstance(comments, list):
                    processed_transcript = await process_full_transcript(transcript, video_id)
                    blog_post = await generate_blog_post(processed_transcript, video_info)
                    formatted_blog_post = format_blog_post(blog_post, video_info)
                    
                    st.markdown(formatted_blog_post, unsafe_allow_html=True)
                    
                    st.subheader("Top Comments")
                    for comment in comments[:5]:  # Limit to 5 comments for performance
                        st.markdown(f"""
                        <div class="comment">
                            <strong>{comment['author']}</strong> - {comment['published_at']}
                            <p>{comment['text']}</p>
                            <small>👍 {comment['likes']}</small>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    end_time = time.time()
                    st.success(f"Blog post generated in {end_time - start_time:.2f} seconds")
                else:
                    st.error("Failed to fetch video information, transcript, or comments.")
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
    else:
        st.info("Enter a YouTube Video ID and click 'Generate' to start.")

if __name__ == "__main__":
    asyncio.run(main())
