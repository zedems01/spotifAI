import os
import json
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
from dotenv import load_dotenv
from openai import OpenAI, APIError

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GEMINI_MODEL = "google/gemini-2.5-flash-preview"
# OPENAI_MODEL = "openai/gpt-4.1" # or "openai/o1", "openai/gpt-4o-2024-11-20",  "openai/o1-preview"
# ANTHROPIC_MODEL = "anthropic/claude-3.7-sonnet"  # or "anthropic/claude-3.7-sonnet:thinking", "anthropic/claude-3.5-haiku", "anthropic/claude-3.5-sonnet" 


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o" # gpt-4.1, o3, o1

# Ensure the model IDs are valid

SCOPES = "user-library-read playlist-modify-public playlist-read-private playlist-read-collaborative"
NEW_PLAYLIST_NAME = "New AI Recommendations"
ALL_RECS_PLAYLIST_NAME = "All AI Recommendations"

TARGET_NEW_SONGS_COUNT = 20
MAX_MODEL_ATTEMPTS = 10 # Increased attempts as we ask for exactly 20 each time
MAX_SONGS_TO_MODEL_PROMPT = 200 # Max liked songs for the initial model prompt

def get_spotify_client():
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPES,
        cache_path=".spotify_cache"
    )
    sp = spotipy.Spotify(auth_manager=auth_manager)
    print("Successfully authenticated with Spotify.")
    return sp


def get_all_liked_songs_details(sp):
    print("Fetching all liked songs details...")
    liked_songs_details = []
    offset = 0
    limit = 50
    while True:
        try:
            results = sp.current_user_saved_tracks(limit=limit, offset=offset)
            if not results or not results['items']:
                break
            for item in results['items']:
                track = item.get('track')
                if track and track.get('name') and track.get('artists'):
                    if track['artists']: # Ensure artist list is not empty
                        artist_name = track['artists'][0]['name']
                        liked_songs_details.append({"track": track['name'], "artist": artist_name})
            offset += limit
            print(f"Fetched {len(liked_songs_details)} liked songs so far...")
            if not results.get('next'):
                break
            time.sleep(0.05)
        except Exception as e:
            print(f"Error fetching liked songs page: {e}")
            break
    print(f"Total liked songs details fetched: {len(liked_songs_details)}")
    return liked_songs_details


def get_playlist_by_name(sp, playlist_name, user_id):
    playlists = sp.current_user_playlists(limit=50)
    while playlists:
        for playlist in playlists['items']:
            if playlist['name'] == playlist_name and playlist['owner']['id'] == user_id:
                return playlist
        if playlists['next']:
            playlists = sp.next(playlists)
            time.sleep(0.05)
        else:
            playlists = None
    return None


def get_or_create_playlist_id(sp, user_id, playlist_name, public=True):
    playlist_object = get_playlist_by_name(sp, playlist_name, user_id)
    if playlist_object:
        print(f"Found existing playlist: '{playlist_name}' (ID: {playlist_object['id']})")
        return playlist_object['id']
    else:
        print(f"Playlist '{playlist_name}' not found. Creating it...")
        try:
            new_playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=public)
            print(f"Successfully created playlist: '{playlist_name}' (ID: {new_playlist['id']})")
            return new_playlist['id']
        except Exception as e:
            print(f"Error creating playlist '{playlist_name}': {e}")
            return None


def get_playlist_tracks_simplified(sp, playlist_id):
    if not playlist_id: return []
    print(f"Fetching tracks from playlist ID: {playlist_id}...")
    playlist_tracks = []
    offset = 0
    limit = 100
    while True:
        try:
            results = sp.playlist_items(playlist_id, limit=limit, offset=offset, fields="items(track(name,artists(name))),next")
            if not results or not results['items']: break
            for item in results['items']:
                track_info = item.get('track')
                if track_info and track_info.get('name') and track_info.get('artists'):
                    if track_info['artists']:
                        artist_name = track_info['artists'][0]['name']
                        playlist_tracks.append({"track": track_info['name'], "artist": artist_name})
            offset += limit
            print(f"Fetched {len(playlist_tracks)} tracks from playlist ID {playlist_id} so far...")
            if not results.get('next'): break
            time.sleep(0.05)
        except Exception as e:
            print(f"Error fetching playlist items for {playlist_id}: {e}")
            break
    print(f"Total tracks fetched from playlist ID {playlist_id}: {len(playlist_tracks)}")
    return playlist_tracks


def get_recommendations_openai(api_key, conversation_history):
    """
    Sends the conversation history to model provider and requests a JSON response.
    Returns a tuple: (parsed_recommendations_list, raw_assistant_response_content_string)
    The last message in conversation_history should ideally instruct the AI to respond in JSON.
    """
    print(f"\nSending request to OpenAI with {len(conversation_history)} messages...")
    if not conversation_history or conversation_history[-1]["role"] != "user":
        print("Error: Conversation history is empty or does not end with a user message.")
        return None, None

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=conversation_history,
            response_format={"type": "json_object"},
            timeout=60.0
        )
        raw_assistant_response_content = response.choices[0].message.content
        if raw_assistant_response_content is None:
            print("Error: OpenAI returned no content. This should not happen with JSON mode.")
            print(f"Full OpenAI Response: {response.model_dump_json(indent=2)}")
            return None, None

        try:
            parsed_json = json.loads(raw_assistant_response_content)["recommendations"]
            print("Successfully parsed JSON response from OpenAI.")
            return parsed_json, raw_assistant_response_content, response
        except json.JSONDecodeError as e:
            print(f"Error: OpenAI response was not valid JSON, despite requesting json_object mode: {e}")
            print(f"OpenAI Raw Response Content:\n{raw_assistant_response_content}")
            return None, raw_assistant_response_content

    except APIError as e:
        print(f"Error calling OpenAI API: {e}")
        if hasattr(e, 'status_code'): print(f"Status code: {e.status_code}")
        if hasattr(e, 'body') and e.body:
             try: print(f"Error body: {json.dumps(e.body)}")
             except: print(f"Error body (raw): {e.body}")
        return None, None
    except Exception as e:
        print(f"An unexpected error occurred: {e.__class__.__name__}: {e}")
        return None, None


def get_recommendations_openrouter(api_key, conversation_history):
    """
    Sends the conversation history to Gemini and requests recommendations.
    Returns a tuple: (parsed_recommendations_list, raw_assistant_response_content_string)
    The last message in conversation_history is assumed to be the current user prompt.
    """
    print(f"\nSending request to Gemini with {len(conversation_history)} messages in history...")
    if not conversation_history or conversation_history[-1]["role"] != "user":
        print("Error: Conversation history is empty or does not end with a user message.")
        return [], None

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": GEMINI_MODEL,
                "messages": conversation_history,
                "response_format": {"type": "json_object"}
            },
            timeout=60 # Increased timeout for potentially longer LLM responses
        )
        response.raise_for_status()
        
        response_data = response.json()
        raw_assistant_response_content = response_data['choices'][0]['message']['content']
        
        recommendations = []
        try:
            parsed_content = json.loads(raw_assistant_response_content)
            if isinstance(parsed_content, list):
                recommendations = parsed_content
            elif isinstance(parsed_content, dict) and len(parsed_content.keys()) == 1:
                key = list(parsed_content.keys())[0]
                if isinstance(parsed_content[key], list):
                    recommendations = parsed_content[key]
        except json.JSONDecodeError:
            print("Gemini response was not directly parsable JSON. Attempting to clean...")
            content_to_parse = raw_assistant_response_content
            if content_to_parse.startswith("```json"): content_to_parse = content_to_parse[7:]
            if content_to_parse.endswith("```"): content_to_parse = content_to_parse[:-3]
            content_to_parse = content_to_parse.strip()
            try:
                parsed_content = json.loads(content_to_parse)
                if isinstance(parsed_content, list): recommendations = parsed_content
                elif isinstance(parsed_content, dict) and len(parsed_content.keys()) == 1:
                    key = list(parsed_content.keys())[0]
                    if isinstance(parsed_content[key], list): recommendations = parsed_content[key]
            except json.JSONDecodeError as e_clean:
                print(f"Error: Gemini response could not be parsed as JSON even after cleaning: {e_clean}")
                print(f"Gemini Raw Response Content:\n{raw_assistant_response_content}")
                return [], raw_assistant_response_content # Return raw content for history even on parse error

        valid_recommendations = []
        for rec in recommendations:
            if isinstance(rec, dict) and "track" in rec and "artist" in rec:
                valid_recommendations.append({"track": str(rec["track"]), "artist": str(rec["artist"])})
            else:
                print(f"Warning: Skipping invalid recommendation format from Gemini: {rec}")
        
        print(f"Received {len(valid_recommendations)} validly structured recommendations from Gemini.")
        return valid_recommendations, raw_assistant_response_content

    except requests.exceptions.RequestException as e:
        print(f"Error calling OpenRouter API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            try: print(f"Response content: {e.response.json()}")
            except json.JSONDecodeError: print(f"Response content: {e.response.text}")
        return [], None
    except (KeyError, IndexError) as e:
        raw_resp_text = response.text if 'response' in locals() else 'No response object'
        print(f"Error parsing Gemini response structure: {e}")
        print(f"Gemini Raw Response (full): {raw_resp_text}")
        return [], None


def verify_songs_on_spotify_v2(sp, recommended_songs_details):
    print("\nVerifying recommended songs on Spotify...")
    available_songs_info = []
    for song_detail in recommended_songs_details:
        track_name = song_detail.get('track')
        artist_name = song_detail.get('artist')
        if not track_name or not artist_name: continue
        query = f"track:{track_name} artist:{artist_name}"
        try:
            results = sp.search(q=query, type="track", limit=1)
            time.sleep(0.05)
            if results and results['tracks']['items']:
                found_track = results['tracks']['items'][0]
                available_songs_info.append({
                    "uri": found_track['uri'],
                    "track": found_track['name'],
                    "artist": found_track['artists'][0]['name']
                })
                print(f"  Found on Spotify: '{found_track['name']}' by {found_track['artists'][0]['name']}")
            else:
                print(f"  Not found on Spotify: '{track_name}' by {artist_name}")
        except Exception as e:
            print(f"  Error searching for '{track_name}' by {artist_name}: {e}")
    print(f"\nVerified {len(available_songs_info)} songs as available on Spotify.")
    return available_songs_info


def update_playlist_items(sp, playlist_id, track_uris, replace=False):
    if not playlist_id: return False
    if not track_uris and not replace: return True
    if not track_uris and replace:
        try:
            sp.playlist_replace_items(playlist_id, [])
            print(f"Cleared all items from playlist ID {playlist_id}.")
            return True
        except Exception as e: print(f"Error clearing playlist {playlist_id}: {e}"); return False

    action = "Replacing" if replace else "Adding"
    print(f"{action} {len(track_uris)} songs for playlist ID {playlist_id}...")
    try:
        if replace:
            # Spotipy's playlist_replace_items handles batching internally up to 100.
            # For >100, it might still be one call to Spotify API that errors,
            # or spotipy might make multiple calls.
            # Let's stick to safer manual batching if >100 for replace.
            if len(track_uris) <= 100:
                 sp.playlist_replace_items(playlist_id, track_uris)
            else:
                sp.playlist_replace_items(playlist_id, []) # Clear
                for i in range(0, len(track_uris), 100):
                    sp.playlist_add_items(playlist_id, track_uris[i:i + 100])
                    time.sleep(0.1)
        else: # Appending
            for i in range(0, len(track_uris), 100):
                sp.playlist_add_items(playlist_id, track_uris[i:i + 100])
                time.sleep(0.1)
        print(f"Successfully {action.lower()}ed songs in playlist ID {playlist_id}.")
        return True
    except Exception as e:
        print(f"Error {action.lower()}ing songs in playlist {playlist_id}: {e}")
        return False

