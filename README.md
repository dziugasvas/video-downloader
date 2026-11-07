# Video Downloader

A small local app for downloading YouTube videos to watch offline. It runs on your Mac and opens in your browser. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org) to do the actual downloading.

- Paste one or more links: single videos or whole playlists
- Quality: **720p**, **1080p**, **Best**, or **Audio only** (m4a)
- Progress bar for each download, with cancel. Two downloads run at a time.
- Choose the folder (default `~/Downloads/Videos`), with **Show in Finder**
- A list of finished files (kept until you quit the app)
- No length limit: 2-hour (or 10-hour) videos work fine

Videos are saved as **mp4 with H.264 video and AAC audio** whenever YouTube offers it, so they play on any Mac, iPhone and iPad. YouTube has no H.264 above 1080p, so **Best** uses AV1 for 1440p/4K. AV1 plays on Apple-silicon Macs and iPhone 15 Pro or newer.

## Setup (once)

You need [Homebrew](https://brew.sh). In Terminal:

```bash
brew install python@3.12 ffmpeg deno
```

> **Why Deno?** YouTube now requires yt-dlp to run some JavaScript to unlock video downloads. Deno is the JavaScript runtime yt-dlp uses for that. You never need to touch it.

Then get the code and start it:

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
chmod +x start.sh update.sh "Video Downloader.command"
./start.sh
```

The first start takes about a minute: the app creates its own Python environment in a `.venv` folder. Your browser then opens at <http://127.0.0.1:8765>.

## Using it

- **Start:** run `./start.sh`, or double-click **Video Downloader.command** in Finder. Keep the Terminal window open while you use the app.
- **Quit:** press `Ctrl+C` in that Terminal window, or just close it.
- **Download:** paste links (one per line), pick a quality, then click **Download** (or press `⌘↵`).
- **Playlists:** a playlist link (`youtube.com/playlist?list=…`) downloads every video into its own subfolder, numbered in order. A link to a single video that happens to be in a playlist (`watch?v=…&list=…`) downloads just that video.
- **Folder:** click **Change…** for the Mac folder picker, or type a path. The app remembers your choice.

The first time you double-click the `.command` file, macOS may say it can't verify it. Right-click it, choose **Open**, then **Open** again. You only need to do this once.

## Keeping yt-dlp up to date

YouTube changes often, and old yt-dlp versions stop working. There are three ways to stay current:

1. **Automatic:** `./start.sh` checks for a new yt-dlp once a day when you start the app.
2. **In the app:** click **Update yt-dlp** at the bottom of the page. No restart needed.
3. **Manually:** run `./update.sh`. This also updates ffmpeg and Deno through Homebrew.

If a download fails with an error mentioning YouTube, updating is the first thing to try. Run `brew upgrade deno` from time to time as well (`update.sh` does it for you).

## Project layout

```
downloader/          The download logic, as its own module (no UI)
  jobs.py            Queue, progress, cancel, history (runs yt-dlp)
  formats.py         Which video/audio formats to pick for each quality
  system.py          Mac helpers: Finder, folder picker, updates
  api.py             FastAPI routes (an APIRouter)
main.py              The app: serves the page and the routes
static/              The page: index.html, style.css, app.js (no build step)
start.sh             Set up + start
update.sh            Update yt-dlp, ffmpeg, Deno
```

## Adding it to another FastAPI app (e.g. as a "Download" tab)

1. Copy the `downloader/` folder into the other app, and add `yt-dlp[default]` to its requirements.
2. Register the routes:

   ```python
   from downloader import DownloadManager, create_router

   download_manager = DownloadManager(max_parallel=2)
   app.include_router(create_router(download_manager), prefix="/api/downloader")
   ```

3. Copy the contents of `<main class="vd">` from `static/index.html` into your tab, and include `static/style.css` and `static/app.js`. Tell the script where the API is with `data-api="/api/downloader"` on `<body>` (or on the element that holds the tab). All CSS classes and element IDs start with `vd-`, so they won't clash with your app.

## Privacy and safety

- The app only listens on your own Mac (`127.0.0.1`) and rejects requests from other websites.
- Nothing is saved inside the project folder. Downloads go to the folder you choose, and the finished list is cleared when you quit.
- `.gitignore` excludes video/audio files and the `.venv` folder, so none of them end up on GitHub.

Only download videos you have the right to save offline. Check YouTube's terms and the creator's rights.
