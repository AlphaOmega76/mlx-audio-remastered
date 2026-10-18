# Chrome Web Store listing: MLX-Audio Reader

Fill these into the dashboard. Items marked (you) need something only you can supply.

## Store listing tab

**Name:** MLX-Audio Reader

**Summary (max 132 characters):**
Read web pages and PDFs aloud with a private, on-device voice. Follow along with highlighting.

**Category:** Accessibility (alternative: Productivity)

**Language:** English

**Description:**

Listen to articles, web pages and PDFs read aloud by natural-sounding AI voices that run entirely
on your own Mac. Nothing you read is sent to the cloud.

IMPORTANT: This extension needs the free MLX-Audio app, which runs the voice on your computer.
It requires an Apple Silicon Mac (M1 or newer). Install it first from:
https://github.com/AlphaOmega76/mlx-audio-remastered/releases
(download MLX-Audio-Installer, then double-click install.command; the extension starts the voice
server for you after that.)

WHAT IT DOES
• Read this page: click the toolbar icon, then Read. The main article is picked out and read aloud.
• Read a selection: select text, right-click, choose "Read aloud with MLX-Audio".
• Follow along: the sentence being spoken is highlighted on the page.
• Controls: pause, skip by paragraph, stop, and a speed slider from 0.5x to 2x.
• PDF reader: open a PDF, click the icon, and read it. Click any sentence to start from there, or
  jump to a page. Repeated and doubled text in awkward PDFs is cleaned up.
• Choose from many voices (American and British, female and male).
• Keeps playing while you work in other tabs.

PRIVATE BY DESIGN
Text goes only to the speech server on your own computer (localhost). No account, no tracking, no
ads. The code is open source.

LIMITS
• Apple Silicon Macs only, Chrome or other Chromium browsers.
• Scanned PDFs without a text layer cannot be read (no OCR).
• Some sites that draw text in a way extensions cannot read (for example in a canvas) will not work;
  selecting the text and using the right-click menu works on most others.

Source code and help: https://github.com/AlphaOmega76/mlx-audio-remastered

## Graphic assets (you)

- Icon 128x128: already in the extension.
- At least one screenshot, 1280x800 (or 640x400): suggest (1) popup reading an article with the
  sentence highlighted, (2) the PDF reader, (3) the settings page.
- Small promo tile 440x280.
- Optional: a short demo video (YouTube link), strongly recommended because reviewers cannot run
  the app themselves.

## Privacy tab

**Single purpose:**
Read the text of web pages and PDFs aloud using a speech server running on the user's own computer.

**Permission justifications:**
- activeTab: reads the text of the page the user chooses to read, only after they click the icon or
  the context-menu item.
- scripting: injects the text-extraction and highlighting script into that page.
- contextMenus: adds "Read aloud with MLX-Audio" for selected text.
- offscreen: hosts the hidden audio player so speech continues while the user uses other tabs.
- storage: saves the user's voice, speed and server-address settings.
- nativeMessaging: lets the extension ask its companion helper to start and stop the local speech
  server. Only start and stop messages are exchanged.
- Host permission http://localhost:8000/* and http://127.0.0.1:8000/*: sends the text to be spoken
  to the user's local speech server and receives the audio.

**Remote code:** No. All code is packaged in the extension.

**Data usage disclosure (tick):** "Website content" (page text is processed to produce speech).
Do not tick the others.
Certify all three: not sold to third parties; not used for unrelated purposes; not used for
creditworthiness or lending.

**Privacy policy URL (you):** publish PRIVACY.md and paste its URL. Once this branch is merged and
pushed, it will be at:
https://github.com/AlphaOmega76/mlx-audio-remastered/blob/main/packaging/chrome-web-store/PRIVACY.md

## Notes for reviewers (Test instructions field)

This extension is the browser front end of an open-source local text-to-speech app. It needs the
companion app on an Apple Silicon Mac to produce speech: download MLX-Audio-Installer-0.5.7.zip
from https://github.com/AlphaOmega76/mlx-audio-remastered/releases, unzip, and double-click
install.command. Then open any article, click the extension icon and press Read. Without the app
installed the popup reports that it cannot reach the local server; this is expected. A demo video
is linked in the listing. All data stays on the local machine.
