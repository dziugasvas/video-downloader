# Shortcuts: "make run" starts the app, "make update" updates yt-dlp.
.PHONY: run update clean help

run: ## Start the app (sets things up on first run)
	@bash ./start.sh

update: ## Update yt-dlp, ffmpeg and Deno
	@bash ./update.sh

clean: ## Remove the app's Python environment (recreated on next run)
	rm -rf .venv

help: ## Show these commands
	@grep -E '^[a-z]+:.*## ' Makefile | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'
