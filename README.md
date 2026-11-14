# Linux Hardware AI Assistant

## 1. Project Overview

Linux Hardware AI Assistant is a local-first hardware monitoring and question-answering application built using Python, Streamlit, Linux system utilities and Ollama.

It allows users to ask natural-language questions about their computer hardware. A locally running Large Language Model (LLM) selects appropriate read-only inspection tools, retrieves system information and generates understandable responses.

**AI Model:** Qwen 2.5 1.5B  
**Backend:** Python  
**Frontend:** Streamlit  
**LLM Runtime:** Ollama

## 2. Key Features

- Natural-language hardware question answering.
- Native Ollama function/tool calling.
- CPU model, physical cores and logical CPU detection.
- RAM usage, free memory and available memory.
- Swap memory monitoring.
- Storage device and disk usage information.
- GPU and PCI device detection.
- Network interface and IP address information.
- RAM topology detection when supported by the environment.
- Follow-up questions using conversation history.
- Read-only system inspection.
- Tool allow-list and argument validation.
- Local LLM processing.

## 3. Project Architecture

The application consists of the following modules:

| File | Description |
|---|---|
| `dashboard.py` | Streamlit user interface |
| `assistant.py` | Ollama integration, conversation management and tool-calling loop |
| `system_tools.py` | Safe, allow-listed Linux hardware inspection tools |
| `hardware.py` | Basic hardware information |
| `hardware_extended.py` | Extended hardware monitoring |
| `requirements.txt` | Python dependencies |
| `tests/` | Automated unit tests |

### Tool-calling workflow

1. User submits a hardware-related question.
2. The question is sent to the local Ollama model.
3. The LLM selects an appropriate inspection tool.
4. Python validates the requested tool name and arguments.
5. The approved read-only inspection function executes.
6. The tool result is returned to the LLM.
7. The LLM generates a natural-language response.
8. Conversation history is retained for follow-up questions.

## 4. Installation Requirements

- Python 3.10 or later.
- Ubuntu or another compatible Linux environment.
- Ollama.
- Qwen 2.5 1.5B model.
- Required Python packages.

Install the dependencies:

```bash
pip install -r requirements.txt
```

## 5. Ollama Setup

Install Ollama and download the model:

```bash
ollama pull qwen2.5:1.5b
```

Check the installed model:

```bash
ollama list
```

Ollama must be running before starting the assistant.

If it is not already running as a background service:

```bash
ollama serve
```

Do not start a second Ollama server if one is already running.

## 6. Running the Application

Navigate to the project directory:

```bash
cd linux-hardware-assistant
```

Activate the virtual environment:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the dashboard:

```bash
python -m streamlit run dashboard.py --server.port 8503
```

Open the application:

```text
http://localhost:8503
```

## 7. Example Questions

Users can ask questions such as:

- What is my CPU model?
- How many physical and logical CPU cores do I have?
- How much RAM is installed?
- How much RAM is currently available?
- Show my swap memory information.
- List my storage devices.
- Show my disk usage.
- What GPU information is available?
- Show my network interfaces.
- How many RAM slots does my system have?

## 8. Security

The application follows a read-only inspection approach.

Security measures include:

- Fixed allow-listed Linux commands.
- No arbitrary user-provided shell execution.
- Tool-name validation.
- Argument validation.
- Subprocess execution without shell interpretation.
- Command execution timeout.
- Graceful handling of unavailable utilities and permissions.

The application does not intentionally modify hardware settings, delete files or terminate processes.

## 9. Automated Testing

Run the automated tests:

```bash
python -m unittest discover -s tests -v
```

The test suite covers:

- CPU information parsing.
- RAM and swap parsing.
- Unauthorized tool rejection.
- Unexpected argument rejection.
- Unknown tool execution prevention.

The current unit test run completed successfully with five passing tests.

## 10. Environment Limitations

When running inside Windows Subsystem for Linux (WSL2), Linux hardware information may represent virtualized resources rather than the complete physical Windows machine.

Some information may not be exposed, including:

- Physical motherboard RAM slot count.
- Maximum motherboard RAM capacity.
- Physical GPU model.
- Detailed physical storage interface information.

The application should report unavailable information rather than inventing hardware specifications.

## 11. Privacy

The application uses a locally running Ollama model for question answering.

Hardware inspection is performed through local Linux utilities. No external LLM API is required for the described local workflow.

## 12. Conclusion

Linux Hardware AI Assistant combines local LLM inference, Python tool execution and Linux system inspection to provide an interactive hardware question-answering experience.

The project demonstrates LLM integration, native tool calling, structured system information parsing, conversation context management and basic command-execution security.