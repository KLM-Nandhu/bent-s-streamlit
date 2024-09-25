import streamlit as st
import openai
from typing import List, Dict
import asyncio
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

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

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

def get_all_comments(video_id: str) -> List[Dict]:
    try:
        comments = []
        nextPageToken = None
        while True:
            response = youtube.commentThreads().list(
                part='snippet',
                videoId=video_id,
                maxResults=100,
                pageToken=nextPageToken,
                order='time'
            ).execute()

            for item in response['items']:
                comment = item['snippet']['topLevelComment']['snippet']
                comments.append({
                    'author': comment['authorDisplayName'],
                    'text': comment['textDisplay'],
                    'likes': comment['likeCount'],
                    'published_at': comment['publishedAt']
                })

            nextPageToken = response.get('nextPageToken')
            if not nextPageToken:
                break

        return comments
    except Exception as e:
        return f"An error occurred while fetching comments: {str(e)}"

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
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that organizes video transcripts without altering their content."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred while processing with GPT-4: {str(e)}"

async def process_full_transcript(transcript: List[Dict], video_id: str) -> str:
    chunk_size = 10000  # Adjust this value based on your needs
    full_transcript = " ".join([f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript])
    chunks = [full_transcript[i:i+chunk_size] for i in range(0, len(full_transcript), chunk_size)]
    
    processed_chunks = []
    for chunk in chunks:
        processed_chunk = await process_transcript_chunk(chunk, video_id)
        processed_chunks.append(processed_chunk)
    
    return "\n\n".join(processed_chunks)

async def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    prompt = f"""Based on the following processed transcript and video information, create a comprehensive blog post. The blog post should include:

1. Title
2. Introduction
3. Main content with subheadings (including timestamps)
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

st.set_page_config(layout="wide")

import streamlit as st

# Define the CSS as a string
import streamlit as st

# Define the CSS as a string
css = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;700&family=Open+Sans:wght@400;600&display=swap');
    
    .blog-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
        background-color: #ffffff;
        box-shadow: 0 0 20px rgba(0,0,0,0.1);
        border-radius: 10px;
    }
    .blog-post {
        font-family: 'Open Sans', sans-serif;
        line-height: 1.8;
        color: #333;
    }
    .blog-post h1 {
        font-family: 'Lora', serif;
        font-size: 2.5em;
        color: #2c3e50;
        text-align: center;
        margin-bottom: 20px;
    }
    .blog-post h2 {
        font-family: 'Lora', serif;
        font-size: 1.8em;
        color: #34495e;
        border-bottom: 2px solid #3498db;
        padding-bottom: 10px;
        margin-top: 30px;
    }
    .blog-post h3 {
        font-family: 'Lora', serif;
        font-size: 1.5em;
        color: #34495e;
    }
    .blog-meta {
        font-size: 0.9em;
        color: #7f8c8d;
        text-align: center;
        margin-bottom: 20px;
    }
    .blog-image {
        max-width: 100%;
        height: auto;
        border-radius: 10px;
        margin: 20px 0;
        box-shadow: 0 0 10px rgba(0,0,0,0.1);
    }
    .product-box {
        background-color: #e8f4fc;
        border: 1px solid #3498db;
        border-radius: 5px;
        padding: 15px;
        margin: 20px 0;
    }
    .product-name {
        font-weight: 600;
        color: #2c3e50;
        font-size: 1.1em;
    }
    .product-url {
        word-break: break-all;
        margin-top: 5px;
    }
    .timestamp {
        font-weight: 600;
        color: #e74c3c;
    }
    .key-moment {
        background-color: #fdf2e9;
        border-left: 4px solid #e67e22;
        padding: 15px;
        margin: 20px 0;
    }
    .comment {
        background-color: #f9f9f9;
        border-left: 4px solid #3498db;
        padding: 15px;
        margin-bottom: 15px;
        border-radius: 5px;
    }
    .comment-author {
        font-weight: 600;
        color: #2c3e50;
    }
    .comment-date {
        font-size: 0.8em;
        color: #7f8c8d;
    }
    .comment-likes {
        font-size: 0.9em;
        color: #3498db;
        margin-top: 5px;
    }
    .blog-content p {
        margin-bottom: 20px;
    }
    blockquote {
        border-left: 5px solid #3498db;
        padding-left: 20px;
        margin: 20px 0;
        font-style: italic;
        color: #34495e;
    }
</style>
"""

# Apply the CSS
st.markdown(css, unsafe_allow_html=True)

# Your existing Streamlit app code goes here
st.title("BENT-S-BLOG")

video_id = st.text_input("Enter YouTube Video ID")

if st.button("Process Transcript and Generate Blog Post"):
    if video_id:
        with st.spinner("Processing transcript and generating blog post..."):
            video_info = get_video_info(video_id)
            if isinstance(video_info, dict):
                transcript = get_video_transcript_with_timestamps(video_id)
                comments = get_all_comments(video_id)
                if isinstance(transcript, list) and isinstance(comments, list):
                    processed_transcript = asyncio.run(process_full_transcript(transcript, video_id))
                    blog_post = asyncio.run(generate_blog_post(processed_transcript, video_info))
                    formatted_blog_post = format_blog_post(blog_post, video_info)
                    
                    # Display the blog post content
                    st.markdown(formatted_blog_post, unsafe_allow_html=True)
                    
                    # Display comments
                    st.markdown("<h2>Comments</h2>", unsafe_allow_html=True)
                    for comment in comments:
                        st.markdown(f"""
                        <div class="comment">
                            <div class="comment-author">{comment['author']}</div>
                            <div class="comment-date">{comment['published_at']}</div>
                            <div class="comment-text">{comment['text']}</div>
                            <div class="comment-likes">👍 {comment['likes']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.error(transcript if isinstance(transcript, str) else comments)
            else:
                st.error(video_info)
    else:
        st.error("Please enter a YouTube Video ID.")

# Updated format_blog_post function
def format_blog_post(blog_post: str, video_info: Dict) -> str:
    formatted_post = f"""
    <div class="blog-container">
        <div class="blog-post">
            <h1>{video_info['title']}</h1>
            <div class="blog-meta">Published on {video_info['published_at']} | {video_info['view_count']} views | {video_info['like_count']} likes</div>
            <img src="{video_info['thumbnail_url']}" alt="{video_info['title']}" class="blog-image"/>
            
            <div class="blog-content">
                {blog_post}
            </div>
        </div>
    </div>
    """
    return formatted_post

# You'll need to implement the logic in generate_blog_post to structure the content
# Here's an example of how you might structure the blog post content:
def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    # This is a placeholder. You'll need to implement the actual logic to generate the blog post
    blog_post = f"""
        <h2>Introduction</h2>
        <p>Welcome to this exciting blog post about {video_info['title']}. In this article, we'll dive deep into the content of this video and explore its key points.</p>

        <blockquote>"{video_info['description'][:100]}..."</blockquote>

        <h2>Main Content</h2>
        <p>This is where you would put the main content of your blog post, based on the processed transcript.</p>

        <h2>Key Moments</h2>
        <div class="key-moment">
            <span class="timestamp">00:05:23</span>
            <p>This is a key moment in the video. You would replace this with actual key moments from the transcript.</p>
        </div>

        <h2>Products Mentioned</h2>
        <div class="product-box">
            <div class="product-name">Example Product</div>
            <div class="product-url"><a href="#" target="_blank">https://example.com/product</a></div>
        </div>

        <h2>Conclusion</h2>
        <p>To wrap up, we've explored the main points of {video_info['title']}. We hope you found this blog post informative and engaging.</p>
    """
    return blog_post
