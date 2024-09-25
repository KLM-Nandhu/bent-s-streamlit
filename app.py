import streamlit as st
import openai
from typing import List, Dict
import asyncio
import requests
from datetime import datetime
import re
import random
import time
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

@st.cache_data
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

@st.cache_data
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

@st.cache_data
def get_video_transcript(video_id: str) -> List[Dict]:
    try:
        return YouTubeTranscriptApi.get_transcript(video_id)
    except Exception as e:
        return f"An error occurred while fetching the transcript: {str(e)}"

def format_time(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

async def process_transcript_chunk(chunk: str, video_id: str) -> str:
    prompt = f"""Organize this video transcript portion into the following structure:

For each distinct topic or section, include:
Product name (if applicable):
Starting timestamp:
Ending Timestamp:
Transcript:

Do not summarize or alter information, just reorganize the existing transcript into this structure. Use the provided timestamps for start and end times.

Transcript chunk:
{chunk}

Format the response as follows:

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
    chunk_size = 10000
    full_transcript = " ".join([f"{format_time(entry['start'])}: {entry['text']}" for entry in transcript])
    chunks = [full_transcript[i:i+chunk_size] for i in range(0, len(full_transcript), chunk_size)]
    
    tasks = [process_transcript_chunk(chunk, video_id) for chunk in chunks]
    processed_chunks = await asyncio.gather(*tasks)
    
    return "\n\n".join(processed_chunks)

async def generate_blog_post(processed_transcript: str, video_info: Dict) -> str:
    prompt = f"""Create a comprehensive blog post based on this processed transcript and video information. Include:

1. Title
2. Introduction
3. Main content with subheadings (including timestamps)
4. Key moments
5. Conclusion
6. Product links (if mentioned in the video)
7. Affiliate information (if provided)
8. Camera and audio equipment used (if mentioned)

Video Title: {video_info['title']}
Video Description: {video_info['description']}

Processed Transcript:
{processed_transcript}

Format the blog post accordingly, ensuring all relevant information from the video description is included. Include product links within the main content where relevant.
"""

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
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
            continue
        elif line.lower().startswith(('introduction', 'conclusion')):
            formatted_post += f"<h2>{line}</h2>"
        elif line.startswith(('###', '##')):
            formatted_post += f"<h3>{line.strip('#').strip()}</h3>"
        elif re.match(r'\d{2}:\d{2}:\d{2}', line):
            timestamp = sum(int(x) * 60 ** i for i, x in enumerate(reversed(line.split(':')[:3])))
            thumbnail_url = f"https://img.youtube.com/vi/{video_info['id']}/{int(timestamp/10)}.jpg"
            formatted_post += f'<img src="{thumbnail_url}" alt="Video thumbnail at {line}" class="timestamp-image">'
            formatted_post += f"<p>{make_links_clickable(line)}</p>"
        elif line.strip() == '':
            formatted_post += "<br>"
        else:
            formatted_post += f"<p>{make_links_clickable(line)}</p>"
    
    return formatted_post

st.set_page_config(layout="wide", page_title="BENT-S-BLOG Generator", page_icon="📝")

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
        background-color: #4CAF50;
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
        transition: background-color 0.3s;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .blog-post {
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
</style>
""", unsafe_allow_html=True)

st.title("BENT-S-BLOG Generator")

video_id = st.text_input("Enter YouTube Video ID")

if st.button("Generate Blog Post"):
    if video_id:
        with st.spinner("Processing video and generating blog post..."):
            # Create placeholder elements for progress updates
            video_info_status = st.empty()
            transcript_status = st.empty()
            comments_status = st.empty()
            processing_status = st.empty()
            blog_post_status = st.empty()

            # Fetch video info, transcript, and comments concurrently
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_video_info = executor.submit(get_video_info, video_id)
                future_transcript = executor.submit(get_video_transcript, video_id)
                future_comments = executor.submit(get_all_comments, video_id)

                video_info = future_video_info.result()
                video_info_status.success("Video information fetched successfully.")

                transcript = future_transcript.result()
                transcript_status.success("Video transcript fetched successfully.")

                comments = future_comments.result()
                comments_status.success("Video comments fetched successfully.")

            if isinstance(video_info, dict) and isinstance(transcript, list) and isinstance(comments, list):
                processing_status.info("Processing transcript...")
                processed_transcript = asyncio.run(process_full_transcript(transcript, video_id))
                processing_status.success("Transcript processed successfully.")

                blog_post_status.info("Generating blog post...")
                blog_post = asyncio.run(generate_blog_post(processed_transcript, video_info))
                formatted_blog_post = format_blog_post(blog_post, video_info)
                blog_post_status.success("Blog post generated successfully.")

                # Display the blog post content
                st.markdown("<div class='blog-post'>", unsafe_allow_html=True)
                st.markdown(formatted_blog_post, unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

                # Display comments in a separate container with internal scrolling
                st.markdown("<div class='comments-container'>", unsafe_allow_html=True)
                st.markdown("<h2>Comments</h2>", unsafe_allow_html=True)
                st.markdown("<div class='comments-scrollable'>", unsafe_allow_html=True)
                for comment in comments:
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
            else:
                error_message = video_info if isinstance(video_info, str) else (transcript if isinstance(transcript, str) else comments)
                st.error(error_message)
    else:
        st.error("Please enter a YouTube Video ID.")

# Add a footer
st.markdown("""
<footer style='text-align: center; padding: 20px; margin-top: 50px; border-top: 1px solid #e0e0e0;'>
    <p>Created by BENT-S-BLOG Generator | &copy; 2023 All Rights Reserved</p>
</footer>
""", unsafe_allow_html=True)
