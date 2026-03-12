# discoder

[日本語](README.md)

Control AI coding agents (Claude Code, etc.) from your phone via Discord.

## Features

- Discord thread = session. Send coding instructions from your phone
- Bidirectional session handoff between terminal and Discord
- Streaming responses (real-time progress with tool execution status)
- Suggested reply buttons (action candidates presented after each response)
- No port forwarding needed (Discord Gateway, outbound connections only)
- Simple operation — just run in tmux

## Setup

### 1. Create a Discord Bot

#### 1-1. Create Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" → enter a name (e.g. `discoder`) → "Create"

#### 1-2. Get Bot Token

1. Open "Bot" in the left menu
2. Click "Reset Token" → copy the displayed token (you'll need it later)
3. Scroll down and turn **ON** "MESSAGE CONTENT INTENT", then "Save Changes"

#### 1-3. Generate Invite URL

1. Open "OAuth2" → "URL Generator" in the left menu
2. Under **SCOPES**, check:
   - `bot`
   - `applications.commands`
3. Under **BOT PERMISSIONS**, check:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Read Message History
4. Copy the generated URL at the bottom of the page

#### 1-4. Invite to Server

1. Open the copied URL in your browser
2. Select the server to invite the bot to
3. Confirm and authorize

> **Tip:** You need "Manage Server" permission to add a bot. If you don't have your own server, create one for free via the "+" button in Discord.

### 2. Install & Run

```bash
pip install discoder
discoder init     # Enter the bot token from step 1-2
discoder start    # Start the bot (recommended to run inside tmux)
```

For development:

```bash
git clone https://github.com/fuumin621/discoder.git
cd discoder
pip install -e .
```

## Usage

### Discord Commands

| Command | Where | Description |
|---|---|---|
| `/new <prompt>` | Channel | Start a new session (`--dir /path` to specify working directory) |
| `/resume [session_id]` | Channel | Resume a session (omit ID for most recent) |
| `/sessions` | Anywhere | List active sessions |
| `/handoff` | Thread | Show session ID and command for terminal handoff |
| `/compact` | Thread | Compress conversation context |
| `/model` | Thread | Switch model (opus / sonnet / haiku) |
| `/cost` | Thread | Show session cost |
| `/stop` | Thread | Stop the current running task |
| `/clear` | Anywhere | Clear all session data |

Simply reply in a thread to continue the conversation.

### Session Handoff

#### Terminal → Discord (continue on your phone)

Open Discord on your phone and run `/resume`. It picks up your most recent terminal session.

#### Discord → Terminal (back at your PC)

Run `claude --continue` in your terminal. It resumes the most recent session (the one you were using on Discord).

```bash
cd /your/project && claude --continue
```

To resume a specific session (e.g. if other sessions were started in between), use `/handoff` in the thread and run the displayed command in your terminal.

### CLI Commands

| Command | Description |
|---|---|
| `discoder init` | Configure bot token |
| `discoder start` | Start the Discord bot |

## Important Notes

- **`--dangerously-skip-permissions` is always enabled.** All Claude Code tools (file editing, arbitrary command execution, etc.) run without confirmation. Discord server access ≈ machine access — **use only on servers with trusted members**
- **Timeout is 15 minutes.** Sessions are interrupted after that. For long-running tasks, instruct Claude to use tmux
- **Image/file attachments are not supported.** Only text messages are processed
- **Messages are queued.** If you send a message while a response is in progress, it will be processed after the current one completes

## Requirements

- Python 3.10+
- Claude Code CLI (`claude` command in PATH, authenticated)
