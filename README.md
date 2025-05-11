# 🎵 SpotifAI

Python script that connects to your Spotify account, analyzes your liked songs, and uses AI to recommend fresh, never-before-suggested tracks—automatically updating your playlist with every run. Run it once or ten times a day — your playlist evolves with you.

---

## 🔧 Setup

### 1. Clone the repo

```bash
git clone https://github.com/zedems01/spotifAI.git
cd spotifAI
```

### 2. Set up a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add environment variables

Create a `.env` file in the root directory and add the following:

```env
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:3000/callback

OPENAI_API_KEY=your_openai_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
```

📌 *You can get your Spotify keys from [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)*   
📌 *OpenRouter API keys can be obtained from [https://openrouter.ai/settings/keys](https://openrouter.ai/settings/keys)*

#### 5. Run the script

```bash
python spotify_playlist.py
```

Each execution will analyze your liked songs and append new, personalized recommendations to your designated playlist.

