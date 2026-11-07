# Video Downloader

A small local app for downloading videos to watch offline, from **YouTube and 1,000+ other sites** ([full list](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)). It runs on your Mac and opens in your browser. Paste links (including playlists), pick a format and quality, and download, with a progress bar for each video.

## Setup (once)

You need [Homebrew](https://brew.sh). In Terminal:

```bash
brew install python@3.12 ffmpeg deno
git clone https://github.com/<your-username>/video-downloader.git
cd video-downloader
chmod +x start.sh update.sh "Video Downloader.command"
```

Deno is needed for YouTube downloads. You never need to touch it.

## How to use

1. **Start:** run `./start.sh`, or double-click **Video Downloader.command** in Finder. The first start takes about a minute. Then your browser opens at <http://127.0.0.1:8765>. Keep the Terminal window open while you use the app.
2. **Download:** paste links (one per line), pick a format and quality, then click **Download** (or press `⌘↵`).
3. **Find your files:** they're saved to `~/Downloads/Videos` by default. Click **Change…** to pick another folder, and use the folder icon next to a finished file to show it in Finder.
4. **Quit:** press `Ctrl+C` in the Terminal window, or close it.

| Format | Best for |
|---|---|
| **MP4** | Everything: iPhone, Samsung/Android, Mac, Windows, TVs |
| **MKV** | Original quality for computers and VLC |
| **MP3** | Audio that plays anywhere |
| **M4A** | Audio at a smaller size, great for podcasts |

Quality: 480p up to 4K, or Best. MP4 above 1080p uses AV1, which plays on most newer devices. Pick 1080p for older phones and TVs.

**If downloads stop working**, YouTube has probably changed something. Click **Update yt-dlp** at the bottom of the app, or run `./update.sh`. The app also checks for updates automatically once a day when it starts.

The first time you open the `.command` file, macOS may say it can't verify it. Right-click it, choose **Open**, then **Open** again.

## Project structure

```
downloader/          Download logic (no UI)
  jobs.py            Queue, progress, cancel, history (runs yt-dlp)
  formats.py         Which streams to pick for each format + quality
  system.py          Mac helpers: Finder, folder picker, updates
  api.py             FastAPI routes
main.py              The app: serves the page and the routes
static/              The page: index.html, style.css, app.js
start.sh             Set up + start
update.sh            Update yt-dlp, ffmpeg and Deno
```

## Credits

Built with the help of [Claude](https://claude.ai) by Anthropic. The downloading itself is done by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org). Please only download videos you have the right to save offline.