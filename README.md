# Comp Crawl

Comp Crawl is a Python-based competitive intelligence tool for crawling competitor websites, detecting changes, and sending scheduled email digests.

## Features

- Crawl configured competitor websites with [Crawl4AI](https://github.com/unclecode/crawl4ai)
- Store crawl results and change history in PostgreSQL
- Use SQLAlchemy for database access
- Generate email digests of detected changes
- Optionally use an LLM through LiteLLM for analysis and summarization
- Run one-off jobs or start a weekly scheduler

## Requirements

- Python 3.10+
- PostgreSQL
- Gmail SMTP credentials for email digests
- An LLM provider, if LLM-powered analysis is enabled

## Installation

```bash
git clone https://github.com/Manujdixit/comp-crawl.git
cd comp-crawl

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

pip install -r requirements.txt
```

Crawl4AI may require additional browser setup. Follow its installation instructions for the browser dependencies required by your environment.

## Configuration

Copy the example environment file and update the values:

```bash
cp .env.example .env
```

At minimum, configure:

- `DATABASE_URL` — PostgreSQL connection string
- `GMAIL_ADDRESS` — Gmail account used to send digests
- `GMAIL_APP_PASSWORD` — Gmail app password
- `DIGEST_RECIPIENTS` — comma-separated recipient addresses
- `LLM_MODEL` and the corresponding provider API key, when using LLM analysis

Never commit `.env` or real credentials to the repository.

## Usage

Initialize the database tables:

```bash
python main.py init
```

Run a one-off crawl and change-detection pass:

```bash
python main.py crawl
```

Send a digest for the latest crawl:

```bash
python main.py digest
```

Send a digest for a specific crawl run:

```bash
python main.py digest <run_id>
```

Start the weekly crawl-and-digest scheduler:

```bash
python main.py run
```

Running `python main.py` without a command prints the available commands.

## Project Structure

```text
.
├── config/       # Application configuration
├── src/          # Crawler, database, email, and scheduler modules
├── templates/    # Email/report templates
├── main.py       # Command-line entry point
├── requirements.txt
└── .env.example  # Environment variable template
```

## Development

The project currently uses a lightweight command-line entry point. When adding functionality, keep provider credentials in environment variables and avoid committing generated crawl data, email output, or secrets.

## License

No license has been specified yet.
