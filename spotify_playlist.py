import os
import json
import random
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
from dotenv import load_dotenv
from openai import OpenAI, APIError
from helper_functions import *

load_dotenv()



if __name__ == "__main__":
    
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REDIRECT_URI and (OPENROUTER_API_KEY or OPENAI_API_KEY)):
        print("Error: Missing environment variables. Please check .env file."); exit(1)

    sp_client = get_spotify_client()
    if not sp_client: exit(1)

    user_info = sp_client.me()
    user_id = user_info['id']
    print(f"Logged in as: {user_info.get('display_name', user_id)}")

    # 1. Get ALL liked songs and create a set for filtering
    all_my_liked_songs_details = get_all_liked_songs_details(sp_client)
    if not all_my_liked_songs_details:
        print("No liked songs found. Exiting."); exit()

    all_my_liked_songs_set = set()
    for song_detail in all_my_liked_songs_details:
        track = song_detail.get('track', "").strip().lower()
        artist = song_detail.get('artist', "").strip().lower()
        if track and artist:
            all_my_liked_songs_set.add((track, artist))
    print(f"Created set of {len(all_my_liked_songs_set)} unique liked songs for de-duplication.")


    # 2. Shuffle liked songs and take a sample for the initial model prompt
    random.shuffle(all_my_liked_songs_details)
    sample_liked_songs_for_model_prompt = all_my_liked_songs_details[:MAX_SONGS_TO_MODEL_PROMPT]

    # Get "All AI Recommendations" playlist history
    all_recs_playlist_id = get_or_create_playlist_id(sp_client, user_id, ALL_RECS_PLAYLIST_NAME)
    existing_all_recs_songs_details = []
    if all_recs_playlist_id:
        existing_all_recs_songs_details = get_playlist_tracks_simplified(sp_client, all_recs_playlist_id)

    all_recs_history_set = set() # Stores (track.lower(), artist.lower()) from "All model Recs" playlist
    for song_detail in existing_all_recs_songs_details:
        track = song_detail.get('track', "").strip().lower()
        artist = song_detail.get('artist', "").strip().lower()
        if track and artist:
            all_recs_history_set.add((track, artist))
    print(f"Found {len(all_recs_history_set)} unique songs in '{ALL_RECS_PLAYLIST_NAME}' history.")


    # 3-5. Iteratively get new recommendations
    collected_new_songs_for_playlist_uris = []
    collected_new_songs_for_playlist_details = [] # Stores Spotify-verified dicts for final playlist

    conversation_history = []
    # Stores dicts {track, artist} of ALL songs the AI model suggests in this session (raw names from the model)
    # Used to tell the model what to avoid in follow-up prompts.
    all_ai_suggestions_this_session_raw_details = [] 

    # Initial user prompt for the very first message to the model
    liked_songs_prompt_str = "\n".join([f"- \"{s['track']}\" by {s['artist']}" for s in sample_liked_songs_for_model_prompt])
    initial_user_prompt_content = f"""You are a music recommendation assistant. I will provide you with a list of songs I like.
    Based on this list, please recommend {TARGET_NEW_SONGS_COUNT} additional songs that I might enjoy.
    It's important that your response is ONLY a valid JSON array of objects, where each object has a "track" key (song title) and an "artist" key (artist name).
    Format example:
    {{
    "recommendations": [
        {{"track": "Bohemian Rhapsody", "artist": "Queen"}},
        {{"track": "Imagine", "artist": "John Lennon"}},
        {{"track": "Smells Like Teen Spirit", "artist": "Nirvana"}}
    ]
    }}
    Do not include any other text, explanations, or markdown formatting outside of the JSON array.

    Here are some songs I like:
    {liked_songs_prompt_str}

    Please provide {TARGET_NEW_SONGS_COUNT} new song recommendations in the specified JSON format."""
    conversation_history.append({"role": "user", "content": initial_user_prompt_content})

    for attempt in range(MAX_MODEL_ATTEMPTS):
        if len(collected_new_songs_for_playlist_uris) >= TARGET_NEW_SONGS_COUNT:
            print("\nTarget number of new songs reached.")
            break

        print(f"\n--- AI Model Request Attempt {attempt + 1}/{MAX_MODEL_ATTEMPTS} ---")
        
        # If this is not the first attempt, construct and add follow-up user message
        if attempt > 0:
            songs_suggested_by_ai_this_session_str = "\n".join(
                [f"- \"{s['track']}\" by {s['artist']}" for s in all_ai_suggestions_this_session_raw_details]
            )
            if not songs_suggested_by_ai_this_session_str:
                songs_suggested_by_ai_this_session_str = "(None previously suggested in this session)"

            follow_up_user_prompt_content = f"""Okay, thank you. Now, please provide {TARGET_NEW_SONGS_COUNT} MORE unique song recommendations based on the initial list of songs I like (provided at the start of our conversation).
    It is very important that these new recommendations are different from any songs you've already suggested to me in this conversation. For reference, here are the songs you've suggested so far (please avoid these):
    {songs_suggested_by_ai_this_session_str}

    Also, ensure these new recommendations are different from the initial list of liked songs I provided.
    Your response must be ONLY a valid JSON array of objects, with "track" and "artist" keys, as before."""
            conversation_history.append({"role": "user", "content": follow_up_user_prompt_content})
            # Prune conversation history if it gets too long (optional, depends on model limits)
            # For now, let it grow for a few turns. Especially if using a model with a decent context window like Gemini Flash.
            # if len(conversation_history) > 10: # Example: keep last 10 messages + initial prompt
            #     conversation_history = [conversation_history[0]] + conversation_history[-9:]

        # print(conversation_history)
        # conversation_history = [{'role': 'user', 'content': 'You are a music recommendation assistant. I will provide you with a list of songs I like.\nBased on this list, please recommend 5 additional songs that I might enjoy.\nIt\'s important that your response is ONLY a valid JSON array of objects, where each object has a "track" key (song title) and an "artist" key (artist name).\nDo not include any other text, explanations, or markdown formatting outside of the JSON array.\n\nHere are some songs I like:\n- "When We Were Young" by Adele\n- "Interlude" by SCH\n- "Cheum" by Nekfeu\n- "Blinding Lights" by The Weeknd\n- "Isoler" by Benab\n- "Sheita" by PNL\n- "Step Into Christmas - Remastered 1995" by Elton John\n- "Spécial (feat. Dosseh)" by Lefa\n- "Skin" by Rihanna\n- "Barillet" by La Fouine\n- "Rude" by Benab\n- "Lettre à la république" by Kery James\n- "999 (with Camilo)" by Selena Gomez\n- "Sinequanone" by Dinos\n- "The Next Episode" by Dr. Dre\n- "Attendez-moi" by Guizmo\n- "Ice Cream (with Selena Gomez)" by BLACKPINK\n- "Bagarre" by Jul\n- "HIBIKI" by Bad Bunny\n- "VS – Call of duty : Modern Warfare III" by Dosseh\n\nPlease provide 5 new song recommendations in the specified JSON format.'}]

        model_batch_recs_parsed, raw_assistant_response_str, raw = get_recommendations_openai(
            OPENAI_API_KEY,
            conversation_history
        )

        # model_batch_recs_parsed, raw_assistant_response_str, raw = get_recommendations_openrouter(
        #     OPENAI_API_KEY,
        #     conversation_history
        # )

        if raw_assistant_response_str: # If the model responded, add its response to history
            conversation_history.append({"role": "assistant", "content": raw_assistant_response_str})
        
        if not model_batch_recs_parsed:
            print("AI Model returned no valid recommendations in this batch or there was an API error.")
            if attempt < MAX_MODEL_ATTEMPTS - 1: time.sleep(3)
            continue

        # Add raw suggestions from this model batch to `all_ai_suggestions_this_session_raw_details`
        # This list helps construct the "avoid these" part of the next follow-up prompt.
        for rec in model_batch_recs_parsed: # rec is dict {track, artist}
            all_ai_suggestions_this_session_raw_details.append(rec)
        
        print(f"AI Model suggested {len(model_batch_recs_parsed)} songs. Verifying on Spotify and filtering...")
        verified_spotify_songs_this_batch = verify_songs_on_spotify_v2(sp_client, model_batch_recs_parsed)
        
        newly_added_this_turn_count = 0
        for verified_song_info in verified_spotify_songs_this_batch: # dict {'uri', 'track', 'artist'}
            if len(collected_new_songs_for_playlist_uris) >= TARGET_NEW_SONGS_COUNT:
                break

            # Use Spotify's canonical track/artist names for consistent checking
            spotify_track_name_lower = verified_song_info['track'].lower()
            spotify_artist_name_lower = verified_song_info['artist'].lower()
            spotify_song_key = (spotify_track_name_lower, spotify_artist_name_lower)
            
            is_liked = spotify_song_key in all_my_liked_songs_set
            is_in_all_recs_playlist_history = spotify_song_key in all_recs_history_set
            
            # Check if URI is already in the list we are building this session
            is_already_collected_for_new_playlist_this_session = any(
                vs['uri'] == verified_song_info['uri'] for vs in collected_new_songs_for_playlist_details
            )

            if not is_liked and not is_in_all_recs_playlist_history and not is_already_collected_for_new_playlist_this_session:
                collected_new_songs_for_playlist_uris.append(verified_song_info['uri'])
                collected_new_songs_for_playlist_details.append(verified_song_info)
                newly_added_this_turn_count +=1
                print(f"  ++ Collected for new playlist: '{verified_song_info['track']}' by '{verified_song_info['artist']}'")
            else:
                reason = []
                if is_liked: reason.append("is liked")
                if is_in_all_recs_playlist_history: reason.append("in all_recs history")
                if is_already_collected_for_new_playlist_this_session: reason.append("already collected this session")
                print(f"  -- Skipped '{verified_song_info['track']}' by '{verified_song_info['artist']}' (Reason: {', '.join(reason)})")

        print(f"Added {newly_added_this_turn_count} new songs this turn.")
        print(f"Total collected for new playlist so far: {len(collected_new_songs_for_playlist_uris)}/{TARGET_NEW_SONGS_COUNT}")
        
        if len(collected_new_songs_for_playlist_uris) >= TARGET_NEW_SONGS_COUNT:
            break 
        elif attempt < MAX_MODEL_ATTEMPTS -1 :
            time.sleep(2) # Pause before next the model attempt

    # --- End of iterative collection ---

    final_uris_for_new_playlist = collected_new_songs_for_playlist_uris[:TARGET_NEW_SONGS_COUNT]
    final_details_for_all_recs_update = collected_new_songs_for_playlist_details[:TARGET_NEW_SONGS_COUNT]

    if not final_uris_for_new_playlist:
        print("\nNo new, verifiable songs were collected from the model after all attempts. Exiting.")
        exit()

    print(f"\nCollected {len(final_uris_for_new_playlist)} final new songs for '{NEW_PLAYLIST_NAME}'.")

    # 5. Save to "New AI Recommendations" (replacing)
    new_playlist_id = get_or_create_playlist_id(sp_client, user_id, NEW_PLAYLIST_NAME)
    if new_playlist_id:
        print(f"\nUpdating playlist '{NEW_PLAYLIST_NAME}' by replacing items...")
        if update_playlist_items(sp_client, new_playlist_id, final_uris_for_new_playlist, replace=True):
            playlist_url_new = sp_client.playlist(new_playlist_id)['external_urls']['spotify']
            print(f"Successfully updated '{NEW_PLAYLIST_NAME}'. URL: {playlist_url_new}")
    else:
        print(f"Could not create or find playlist '{NEW_PLAYLIST_NAME}'.")

    # 6. Add these songs to "All AI Recommendations" (appending)
    if all_recs_playlist_id and final_details_for_all_recs_update: # Use details to get URIs
        uris_to_add_to_all_recs = [song['uri'] for song in final_details_for_all_recs_update]
        print(f"\nAppending {len(uris_to_add_to_all_recs)} songs to '{ALL_RECS_PLAYLIST_NAME}'...")
        if update_playlist_items(sp_client, all_recs_playlist_id, uris_to_add_to_all_recs, replace=False):
            playlist_url_all = sp_client.playlist(all_recs_playlist_id)['external_urls']['spotify']
            print(f"Successfully appended songs to '{ALL_RECS_PLAYLIST_NAME}'. URL: {playlist_url_all}")
    elif not all_recs_playlist_id:
            print(f"Could not find or create playlist '{ALL_RECS_PLAYLIST_NAME}' to append songs.")

    print("\nScript finished :) !!!.")

