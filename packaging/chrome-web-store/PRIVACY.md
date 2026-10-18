# Privacy Policy: MLX-Audio Reader

*Last updated: 18 October 2026*

MLX-Audio Reader is a Chrome extension that reads web pages and PDFs aloud using a speech server
that runs **on your own Mac**. It has no account, no analytics, no advertising and no server of ours.

## What the extension handles

- **Page text.** When you press Read (or choose "Read aloud with MLX-Audio" on selected text), the
  extension reads the text of the current page, or of your selection, in your browser. This text is
  sent to the MLX-Audio speech server at the address in the extension's settings, by default
  `http://localhost:8000`, which is a program running on your own computer. The text is used only to
  generate speech and is not stored by the extension.
- **PDFs.** When you open the PDF reader, the PDF file is sent to the same local server so its text
  can be extracted. It is not kept by the extension.
- **Settings.** Your chosen voice, speed, speaking style and server address are saved in Chrome's
  extension storage (`chrome.storage.local`) on your computer. They are never sent anywhere.

## What we do not do

- We do not collect, receive, sell or share your data. The developer never sees the pages you read.
- We do not use remote code, trackers or third-party analytics.
- The extension makes no network requests to anyone but the speech server address you configured.
  If you change that address to a server on another machine, the text you read is sent to that
  server, and you are responsible for trusting it.

## Permissions, and why

- **activeTab, scripting:** read the text of the page you ask it to read and highlight the sentence
  being spoken.
- **contextMenus:** the right-click "Read aloud" entry for selected text.
- **offscreen:** a hidden page that plays the audio, so it keeps playing while you use other tabs.
- **storage:** remember your settings.
- **nativeMessaging:** talk to a small helper installed with the MLX-Audio app that starts the local
  speech server when you press Read and stops it when Chrome closes. It exchanges only start/stop
  messages.
- **Access to localhost:8000:** send text to your local speech server.

## The MLX-Audio app and server

The speech server is a separate program you install from the project's GitHub page. It runs
locally. On first use it downloads voice models from Hugging Face; no page text is sent in that
download. Its own code is public so you can inspect it.

## Contact

Questions or concerns: open an issue at
https://github.com/AlphaOmega76/mlx-audio-remastered/issues

If this policy changes, the new version will be published at the same address with a new date.
