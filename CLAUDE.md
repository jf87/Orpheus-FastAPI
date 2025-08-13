# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Orpheus-FastAPI is a high-performance Text-to-Speech server that provides an OpenAI-compatible API for generating multilingual speech from text. The system uses a neural audio codec (SNAC) to convert text into expressive speech with 24 different voices across 8 languages.

## Development Commands

### Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install PyTorch with CUDA support (GPU)
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Install PyTorch with ROCm support (AMD GPU)
pip3 install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/rocm6.4/

# Install dependencies
pip3 install -r requirements.txt

# Create necessary directories
mkdir -p outputs static
```

### Running the Server
```bash
# Direct execution
python app.py

# Or with uvicorn for development
uvicorn app:app --host 0.0.0.0 --port 5005 --reload
```

### Docker Development
```bash
# GPU support (CUDA)
docker compose -f docker-compose-gpu.yml up

# GPU support (ROCm)
docker compose -f docker-compose-gpu-rocm.yml up

# CPU-only support
docker compose -f docker-compose-cpu.yml up
```

### Testing the API
```bash
# Test OpenAI-compatible endpoint
curl http://localhost:5005/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "orpheus",
    "input": "Hello world! This is a test.",
    "voice": "tara",
    "response_format": "wav"
  }' \
  --output test.wav

# Test legacy endpoint
curl -X POST http://localhost:5005/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world!", "voice": "tara"}' \
  -o test.wav
```

## Architecture

### Core Components

1. **FastAPI Server (`app.py`)**
   - Handles HTTP requests and serves web UI
   - Provides OpenAI-compatible `/v1/audio/speech` endpoint
   - Legacy `/speak` endpoint for simple requests
   - Environment variable management with `.env` file support
   - Server configuration UI accessible via web interface

2. **TTS Engine (`tts_engine/`)**
   - `inference.py`: Token generation and LLM API communication
   - `speechpipe.py`: Audio conversion using SNAC model
   - Supports 24 voices across 8 languages with emotion tags

3. **Hardware Optimization**
   - Automatic detection of GPU capabilities (High-end, Standard, CPU-only)
   - Dynamic parameter adjustment based on hardware
   - CUDA acceleration with memory optimization

### Key Design Patterns

- **Two-stage pipeline**: Text → Tokens (via LLM) → Audio (via SNAC)
- **Batched processing**: Long text automatically split and stitched with crossfades
- **Environment-driven configuration**: All settings configurable via `.env` file
- **Hardware-aware optimization**: Automatic parameter tuning based on GPU capabilities

### External Dependencies

The system requires a separate LLM inference server running the Orpheus model:
- Supported: GPUStack, LM Studio, llama.cpp server, or any OpenAI-compatible API
- Model variants: Q2_K (fastest), Q4_K_M (balanced), Q8_0 (highest quality)
- Configuration via `ORPHEUS_API_URL` environment variable

## Configuration

### Environment Variables (.env file)
- `ORPHEUS_API_URL`: LLM inference server URL (default: http://127.0.0.1:1234/v1/completions)
- `ORPHEUS_API_TIMEOUT`: API request timeout in seconds (default: 120)
- `ORPHEUS_MAX_TOKENS`: Maximum tokens to generate (default: 8192)
- `ORPHEUS_TEMPERATURE`: Generation temperature (default: 0.6)
- `ORPHEUS_TOP_P`: Top-p sampling (default: 0.9)
- `ORPHEUS_SAMPLE_RATE`: Audio sample rate (default: 24000)
- `ORPHEUS_MODEL_NAME`: Model name for inference server
- `ORPHEUS_PORT`: Web server port (default: 5005)
- `ORPHEUS_HOST`: Web server host (default: 0.0.0.0)

### Voice Configuration
Available voices are defined in `AVAILABLE_VOICES` in `tts_engine/inference.py`. Includes:
- English: tara, leah, jess, leo, dan, mia, zac, zoe
- French: pierre, amelie, marie
- German: jana, thomas, max
- Korean: 유나, 준서
- Hindi: ऋतिका
- Mandarin: 长乐, 白芷
- Spanish: javi, sergio, maria
- Italian: pietro, giulia, carlo

### Emotion Tags
Supported emotion tags for expressive speech:
`<laugh>`, `<sigh>`, `<chuckle>`, `<cough>`, `<sniffle>`, `<groan>`, `<yawn>`, `<gasp>`

## Development Notes

- Python 3.8-3.11 supported (3.12 not supported due to pkgutil.ImpImporter removal)
- Repetition penalty hardcoded to 1.1 for optimal quality (cannot be changed)
- Token processing uses 49-token context window (7²) with 7-token batches for mathematical alignment
- Long text processing includes intelligent sentence splitting and crossfade stitching
- System automatically creates `.env` from `.env.example` if missing
- Web UI provides real-time configuration management and server restart capabilities

## Integration

### OpenWebUI Integration
Configure as TTS provider:
1. Set TTS to "OpenAI" mode
2. API Base URL: `http://localhost:5005/v1`
3. API Key: "not-needed"
4. TTS Voice: any available voice name
5. TTS Model: "tts-1"

### Performance Optimization
- High-end GPUs (16GB+ VRAM or 8.0+ compute capability): 4 workers, 32-token batches
- Standard GPUs: Balanced parameters with CUDA acceleration
- CPU mode: 2 workers, 16-token batches, conservative memory usage