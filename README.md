# Materials Research Paper Analysis System

An automated system for analyzing academic papers based on Materials Project material IDs.

## Features

- Fetch material properties from Materials Project API
- Search papers using Semantic Scholar API
- AI-powered paper filtering with Google Gemini
- Download PDFs from Elsevier and Anna Archive
- Generate structured analysis reports

## Requirements

- Python 3.8+
- API keys for Materials Project, Google Gemini, and Elsevier

## Installation

```bash
git clone https://github.com/yourusername/paper-search-agent.git
cd paper-search-agent
python3 -m venv paper
source paper/bin/activate
pip install -r requirements.txt
cp .env.template .env
# Edit .env with your API keys
```

## Usage

```bash
python run.py
```

Enter a Materials Project ID (e.g., `mp-20738` or `20738`) and target paper count.

## Configuration

Required API keys in `.env`:
- `MP_API_KEY` - [Materials Project](https://next-gen.materialsproject.org/api)
- `GEMINI_API_KEY` - [Google Gemini](https://aistudio.google.com/apikey)  
- `ELSEVIER_API_KEY` - [Elsevier](https://dev.elsevier.com/apikey/manage)
- `ANNA_ARCHIVE_API_KEY` - [Anna'archive](https://annas-archive.org/donate)
- `SEMANTIC_SCHOLAR_API_KEY` - [Semantic Scholar](https://www.semanticscholar.org/product/api)
- `WITHIN_INSTITUTIONAL_IP` - Set to true if your network has Elsevier institutional access for full text retrieval; otherwise, set to false and enable Anna's Archive for full text access.

## Output

Results are saved in `results/mp-{id}-{timestamp}/`:
- Paper metadata (CSV)
- Analysis results (CSV/TXT)
- Downloaded PDFs
- Summary report

## License

MIT