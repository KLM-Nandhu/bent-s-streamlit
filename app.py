import streamlit as st
import openai
from typing import List, Dict, Tuple
import asyncio
import aiohttp
import requests
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
from functools import lru_cache

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

@lru_cache(maxsize=100)
def get_video_info(video_id: str) -> Dict:
    try:
        response = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            id=video_id
        ).execute()

        video_data = response['items'][0]
        return {
            'id': video_id,
            'title': video_data['snippet']['title'],
            'description': video_data['snippet']['description'],
            'thumbnail_url': video_data['snippet']['thumbnails']['high']['url'],
            'view_count': video_data['statistics']['viewCount'],
            'like_count': video_data['statistics']['likeCount'],
            'duration': video_data['contentDetails']['duration'],
            'published_at': video_data['snippet']['publishedAt']
        }
    except Exception as e:
        return f"An error occurred while fetching video info: {str(e)}"

async def get_comments_page(session, video_id: str, page_token: str = None) -> Tuple[List[Dict], str]:
    try:
        url = f"https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={video_id}&key={YOUTUBE_API_KEY}&maxResults=100&order=time"
        if page_token:
            url += f"&pageToken={page_token}"
        
        async with session.get(url) as response:
            data = await response.json()
            
        comments = [
            {
                'author': item['snippet']['topLevelComment']['snippet']['authorDisplayName'],
                'text': item['snippet']['topLevelComment']['snippet']['textDisplay'],
                'likes': item['snippet']['topLevelComment']['snippet']['likeCount'],
                'published_at': item['snippet']['topLevelComment']['snippet']['publishedAt']
            }
            for item in data['items']
        ]

        next_page_token = data.get('nextPageToken')
        return comments, next_page_token

    except Exception as e:
        return f"An error occurred while fetching comments: {str(e)}", None

async def get_all_comments(video_id: str) -> List[Dict]:
    async with aiohttp.ClientSession() as session:
        all_comments = []
        next_page_token = None
        
        while True:
            comments, next_page_token = await get_comments_page(session, video_id, next_page_token)
            if isinstance(comments, list):
                all_comments.extend(comments)
            
            if not next_page_token:
                break
        
        return all_comments

@lru_cache(maxsize=100)
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
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi.get_transcript(video_id)

def fetch_transcript_with_rotating_proxy(video_id: str) -> List[Dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
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
    # You would need to replace this with an actual API call to a service that provides YouTube transcripts
    api_url = f"https://api.transcriptservice.com/v1/youtube/{video_id}"
    response = requests.get(api_url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Third-party API request failed with status code {response.status_code}")

def fetch_transcript_with_custom_headers(video_id: str) -> List[Dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
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

def chunk_transcript(transcript: List[Dict], chunk_size: int = 1000) -> List[str]:
    full_text = " ".join(f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript)
    return [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]

async def process_transcript_chunk(chunk: str) -> str:
    prompt = f"Summarize this transcript chunk: {chunk}"
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",  # Use a faster model for initial processing
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150  # Limit the response size
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while processing with GPT-3.5-turbo: {str(e)}"

async def process_full_transcript(transcript: List[Dict]) -> str:
    chunks = chunk_transcript(transcript)
    summaries = await asyncio.gather(*[process_transcript_chunk(chunk) for chunk in chunks])
    return " ".join(summaries)

async def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    prompt = f"""Based on the following processed transcript and video information, create a comprehensive blog post. The blog post should include:

1. Title
2. Introduction
3. Main content with subheadings (including timestamps with 5 to 8 lines in a content)
4. Key moments
5. Conclusion
6. Product links (if any mentioned in the video)
7. Affiliate information (if provided)
8. Camera and audio equipment used (if mentioned)

Video Title: {video_info['title']}
Video Description: {video_info['description']}

Processed Transcript:
{processed_transcript}

Please format the blog post accordingly, ensuring all relevant information from the video description is included. Include product links within the main content where relevant.
"""

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates detailed blog posts from video transcripts and information."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while generating the blog post: {str(e)}"

def get_image_html(img_url: str, alt_text: str) -> str:
    return f'<img src="{img_url}" alt="{alt_text}" class="blog-image"/>'

def make_links_clickable(text: str) -> str:
    return re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank">\1</a>', text)

def format_blog_post(blog_post: str, video_info: Dict) -> str:
    lines = blog_post.split('\n')
    formatted_post = f"<h1>{video_info['title']}</h1>"
    formatted_post += f"<div class='blog-meta'>Published on {video_info['published_at']} | {video_info['view_count']} views | {video_info['like_count']} likes</div>"
    formatted_post += get_image_html(video_info['thumbnail_url'], video_info['title'])
    
    for line in lines:
        if line.startswith('Title:'):
            continue  # Skip the title as we've already added it
        elif line.lower().startswith(('introduction', 'conclusion')):
            formatted_post += f"<h2><strong>{line}</strong></h2>"
        elif line.startswith(('###', '##')):
            formatted_post += f"<h3><strong>{line.strip('#').strip()}</strong></h3>"
        elif re.match(r'\d{2}:\d{2}:\d{2}', line):  # Check for timestamp
            timestamp = sum(int(x) * 60 ** i for i, x in enumerate(reversed(line.split(':')[:3])))
            thumbnail_url = f"https://img.youtube.com/vi/{video_info['id']}/{int(timestamp/10)}.jpg"
            formatted_post += f'<img src="{thumbnail_url}" alt="Video thumbnail at {line}" style="width: 320px; height: 180px; object-fit: cover;">'
            formatted_post += f"<p>{make_links_clickable(line)}</p>"
        elif line.strip() == '':
            formatted_post += "<br>"
        else:
            formatted_post += f"<p>{make_links_clickable(line)}</p>"
    
    return formatted_post

async def process_video(video_id: str):
    video_info = get_video_info(video_id)
    transcript = get_video_transcript_with_timestamps(video_id)
    
    # Run these tasks concurrently
    comments_task = asyncio.create_task(get_all_comments(video_id))
    transcript_task = asyncio.create_task(process_full_transcript(transcript))
    
    comments = await comments_task
    processed_transcript = await transcript_task
    
    blog_post = await generate_blog_post(processed_transcript, video_info)
    formatted_blog_post = format_blog_post(blog_post, video_info)
    
    return video_info, formatted_blog_post, comments

st.set_page_config(layout="wide")
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
    
    body {
        color: #333;
        font-family: 'Roboto', sans-serif;
        line-height: 1.6;
        background-color: #f0f2f5;
    }
    .main {
        max-width: 1200px;
        margin: 0 auto;
        padding: 2rem;
    }
    .stButton>button {
        width: 100%;
        background-color: #3498db;
        color: white;
        border: none;
        padding: 12px 20px;
        text-align: center;
        text-decoration: none;
        display: inline-block;
        font-size: 18px;
        margin: 4px 2px;
        cursor: pointer;
        border-radius: 5px;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #2980b9;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    }
    .content-container {
        margin-top: 2rem;
        background-color: white;
        padding: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        border-radius: 8px;
    }
    .blog-post h1 {
        font-size: 2.8em;
        color: #2c3e50;
        margin-bottom: 0.5em;
        border-bottom: 2px solid #3498db;
        padding-bottom: 10px;
        font-weight: 700;
    }
    .blog-post h2 {
        font-size: 2.2em;
        color: #34495e;
        margin-top: 1.2em;
        margin-bottom: 0.5em;
        font-weight: 700;
        border-left: 4px solid #3498db;
        padding-left: 10px;
    }
    .blog-post h3 {
        font-size: 1.8em;
        color: #34495e;
        margin-top: 1em;
        margin-bottom: 0.5em;
        font-weight: 600;
    }
    .blog-post p {
        margin-bottom: 1em;
        text-align: justify;
        font-size: 1.1em;
        line-height: 1.8;
    }
    .blog-meta {
        font-size: 0.9em;
        color: #7f8c8d;
        margin-bottom: 1em;
    }
    .blog-image {
        max-width: 100%;
        height: auto;
        margin: 1em 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .timestamp-image {
        width: 320px;
        height: 180px;
        object-fit: cover;
        border-radius: 4px;
        margin: 10px 0;
    }
    .comments-container {
        margin-top: 2rem;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 20px;
        background-color: #f9f9f9;
    }
    .comments-scrollable {
        max-height: 500px;
        overflow-y: auto;
    }
    .comment {
        background-color: #ffffff;
        border-left: 4px solid #3498db;
        padding: 15px;
        margin-bottom: 15px;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    .comment-author {
        font-weight: bold;
        color: #2c3e50;
    }
    .comment-date {
        font-size: 0.8em;
        color: #7f8c8d;
    }
    .comment-text {
        margin-top: 5px;
    }
    .comment-likes {
        font-size: 0.9em;
        color: #3498db;
        margin-top: 5px;
    }
    a {
        color: #3498db;
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }
    .loading-spinner {
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100px;
    }
    .waiting-message {
        text-align: center;
        font-size: 1.2em;
        color: #3498db;
        margin-top: 20px;
    }
    .total-time {
        text-align: right;
        font-size: 0.9em;
        color: #7f8c8d;
        margin-top: 10px;
    }
</style>
""", unsafe_allow_html=True)

st.title("BENT-S-BLOG")

video_id = st.text_input("Enter YouTube Video ID")

if st.button("Click To Generate"):
    if video_id:
        start_time = time.time()
        with st.spinner("Processing video..."):
            video_info, formatted_blog_post, comments = asyncio.run(process_video(video_id))
            
            # Display the content
            st.markdown("<div class='content-container'>", unsafe_allow_html=True)
            
            st.markdown("<div class='blog-post'>", unsafe_allow_html=True)
            st.markdown(formatted_blog_post, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='comments-container'>", unsafe_allow_html=True)
            st.markdown("<h2>Comments</h2>", unsafe_allow_html=True)
            st.markdown("<div class='comments-scrollable'>", unsafe_allow_html=True)
            for comment in comments[:100]:  # Limit to first 100 comments for performance
                st.markdown(f"""
                <div class="comment">
                    <div class="comment-author">{comment['author']}</div>
                    <div class="comment-date">{comment['published_at']}</div>
                    <div class="comment-text">{comment['text']}</div>
                    <div class="comment-likes">👍 {comment['likes']}</div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
            end_time = time.time()
            total_time = end_time - start_time
            st.markdown(f"<div class='total-time'>Total time taken: {total_time:.2f} seconds</div>", unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.error("Please enter a YouTube Video ID.")
