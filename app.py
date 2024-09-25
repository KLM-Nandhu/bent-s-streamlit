import streamlit as st
from typing import List, Dict
import asyncio
import openai
from googleapiclient.discovery import build
import re
from html import unescape
from datetime import datetime

# Set your API keys here
openai.api_key = st.secrets["OPENAI_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

# YouTube API setup
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
    try:
        captions = youtube.captions().list(
            part='snippet',
            videoId=video_id
        ).execute()

        if 'items' not in captions or len(captions['items']) == 0:
            return "No captions found for this video."

        caption_id = captions['items'][0]['id']
        subtitle = youtube.captions().download(
            id=caption_id,
            tfmt='srt'
        ).execute()

        # Decode the subtitle content
        subtitle_text = subtitle.decode('utf-8')

        # Parse the SRT format
        subtitle_parts = re.split(r'\n\n', subtitle_text.strip())
        transcript = []

        for part in subtitle_parts:
            lines = part.split('\n')
            if len(lines) >= 3:
                time_range = lines[1].split(' --> ')
                start_time = time_to_seconds(time_range[0])
                text = ' '.join(lines[2:])
                transcript.append({
                    'start': start_time,
                    'text': unescape(text)
                })

        return transcript

    except Exception as e:
        return f"An error occurred while fetching the transcript: {str(e)}"

def time_to_seconds(time_str: str) -> float:
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s.replace(',', '.'))

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
        max-width: 800px;
        margin: 0 auto;
        background-color: white;
        padding: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        border-radius: 8px;
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
    .blog-content {
        background-color: #fff;
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .blog-image {
        max-width: 100%;
        height: auto;
        margin: 1em 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .comments-container {
        max-width: 800px;
        margin: 2rem auto;
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
</style>
""", unsafe_allow_html=True)

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
                    st.markdown("<div class='blog-post'>", unsafe_allow_html=True)
                    st.markdown("<div class='blog-content'>", unsafe_allow_html=True)
                    st.markdown(formatted_blog_post, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
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
                    st.error(transcript if isinstance(transcript, str) else comments)
            else:
                st.error(video_info)
    else:
         st.error("Please enter a YouTube Video ID.")
