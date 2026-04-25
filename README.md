# MindMup2 Google Drive MCP Server

A Model Context Protocol (MCP) server that provides seamless integration between MindMup mind maps and Google Drive. This server enables you to search, retrieve, and parse MindMup files stored in your Google Drive directly through the MCP interface.

## 💫 Result
![ezgif-5b4a0eb3a275f8.gif](readme/ezgif-5b4a0eb3a275f8.gif)

## ✨ Feature

- **Search MindMup Files**: Find MindMup files across your entire Google Drive (read-only)
- **Google Drive Integration**: List and filter files in Google Drive with various criteria
- **MindMup Parsing**: Parse and extract content from MindMup mind map files
- **FastMCP Server**: Built on FastMCP framework for high performance
- **Docker Support**: Containerized deployment with Docker Compose

## 🔧 Available MCP Tools

| Tool | Description |
|------|-------------|
| `list_files` | List MindMup files from Google Drive (folders and non-MindMup files filtered by default), returns folder URL for each file |
| `read_mindmap` | Read a MindMup file by ID or name. Small files return full AI-friendly content; large files return tree outline + section stats with drill-down hint |
| `search_mindmap` | Search nodes in a mindmap by keyword, returns matching nodes with `node_path` for follow-up drill-down |
| `get_mindmap_section` | Drill into a specific section by `node_path` (e.g. `1.2.3`). Auto switches to outline mode if section is still too large |


## 🏗️ Project Structure

```
├── mcp_deployment/
│   ├── docker-compose-dev.yml
│   ├── docker-compose-prod.yml
│   └── Dockerfile
├── src/
│   ├── core/
│   │   ├── gdrive_client.py    # Google Drive API client
│   │   ├── gdrive_feature.py   # Google Drive feature implementation
│   │   ├── mcp_server.py       # Main MCP server with read tools
│   │   └── mindmup_parser.py   # MindMup parsing + tree navigation
│   ├── model/
│   │   ├── common_model.py     # Common data models
│   │   ├── gdrive_model.py     # Google Drive data models
│   │   └── mindmup_model.py    # Mind map data models (with to_ai_dict)
│   └── utility/
│       ├── enum.py             # Enumerations and constants
│       └── logger.py           # Logging utilities
├── tests/                      # Unit tests
├── plans/                      # Implementation plans
├── run.py                      # Main entry point
├── requirements.txt            # Python dependencies
└── makefile                    # Build and deployment commands
```

## 🚀 Getting Started

### Prerequisites
- Python 3.12+
- Google Cloud Platform account

### Google Drive API Setup

| Step | Description                                                                                                                                                                                | Image |
|------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-|
| 1 | Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project or select an existing one                                                                         | |
| 2 | Enable [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) in your project                                                                              | |
| 3 | Create Service Account credentials:<br>- Go to "IAM & Admin" → "Service Accounts"<br>- Click "Create Service Account"<br>- Download the JSON key file                                      | ![google_service_acc.jpg](readme/google_service_acc.jpg)|
| 4 | Encode the entire JSON key file to base64:<br>- See [Generate Base64 Credential](#generate-base64-credential) section                                                                      | |
| 5 | Share your Google Drive folder with the Service Account:<br>- Right-click folder → Share<br>- Paste the service account email<br>- Grant **Viewer** access<br>- Do **NOT** send invitation |![google_drive_share_list2.jpg](readme/google_drive_share_list2.jpg)|

### Run the Server
For development:
```bash
make run-dev-docker
```

For production:
```bash
make run-prod
```
### MCP Client Configuration
Add this server to your MCP client configuration:

```json
{
    "mcpServers": {
        "mindmup-gdrive": {
            "type": "http",
            "url": "http://127.0.0.1:9805/mcp",
            "headers": {
                "X-Google-Credential": "BASE64_GOOGLE_SERVICE_JSON_BODY",
                "X-Client-Id": "YOUR_UNIQUE_ID"
            }
        }
    }
}
```

#### Generate Base64 Credential
Encode your Google service account JSON to base64:
https://www.base64encode.org/
Copy the output and paste it as the `X-Google-Credential` value.

#### About `X-Client-Id`
A unique identifier per user + tool combination (e.g. `shyin-claude-code`, `shyin-cursor`).

The server uses `(X-Client-Id, credential_hash, file_id)` as cache key to isolate
each user's file cache, so different AI clients (or different machines) don't share
each other's cached content.

- If omitted, falls back to `default` and a warning is logged. Cache may then be
  shared with anyone else who also didn't set the header.
- Recommended format: `<your-name>-<tool-name>`, e.g. `shyin-claude-code`.

Exmaple
```json
{
    "mcpServers": {
        "mindmup-gdrive": {
            "type": "http",
            "url": "http://127.0.0.1:9805/mcp",
            "headers": {
                "X-Google-Credential": "ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb3VuXXXXXXXXXXX",
                "X-Client-Id": "shyin-claude-code"
            }
        }
    }
}
```

