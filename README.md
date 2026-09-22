# VoiceMe

VoiceMe is a simple voice AI assistant that runs locally on your computer.

You can open it in your browser, press **Talk**, speak to it, and hear the AI respond. The entire conversation is handled on your own machine using open-source tools, so there is no API key, account, or cloud AI service required.

## How it works

VoiceMe uses a few different tools, each handling a specific part of the conversation:

| Job | Tool | License |
| --- | --- | --- |
| Speech-to-text | [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) | MIT |
| Language model | [Ollama](https://ollama.com/) with `phi4-mini` | See model license |
| Text-to-speech | [Piper](https://github.com/OHF-Voice/piper1-gpl) | GPL-3.0-or-later |
| Web server | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) | MIT / BSD |
| Frontend | HTML, CSS and JavaScript | This repository |

When you speak, Faster-Whisper converts your voice into text. The text is then sent to the local Ollama model, which generates a response. Piper converts that response back into speech so you can hear it.

Everything happens locally.

## What you can do

VoiceMe is designed to feel like a simple voice conversation rather than a traditional chatbot.

- Press **Talk** or the space bar to speak.
- VoiceMe automatically detects when you stop talking.
- Your speech is transcribed locally.
- The AI response starts playing as soon as the first sentence is ready.
- You can interrupt the assistant while it is speaking.
- You can enable **Keep listening after each reply** for a more natural, hands-free conversation.
- Conversation history is kept during the current session.

## Requirements

Before running VoiceMe, you will need:

- Python 3.10 or newer
- Python 3.11 or 3.12 recommended
- Ollama
- A working microphone
- A modern browser such as Chrome, Edge, Firefox, or Safari

## Getting started

### 1. Install Ollama

Download and install Ollama from:

https://ollama.com/download

After installing it, open PowerShell or a terminal and download the default model:

```bash
ollama pull phi4-mini
