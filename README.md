# RAK Court Judgments Scraper

This project automates scraping court judgment data from the Ras Al Khaimah (RAK) judicial portal using Selenium and Python.

## Project Overview

* **`app.py`**: Flask application to manage HTTP requests and scraping logic.
* **`main.py`**: Standalone scraper for manual execution without Flask.
* **`rak_scrape.py`**: Script for triggering scraping with predefined parameters.
* **`requirements.txt`**: Python dependencies required by the project.

## Setup

1. **Install Dependencies**:

```sh
pip install -r requirements.txt
```

2. **Run the Scraper**:

* For Flask-based scraping:

```sh
python app.py
```

* For manual scraping:

```sh
python main.py
```

## Usage

* Send requests to the Flask endpoint with required parameters (e.g., court type, year) or manually edit parameters in scripts.

## Output

Scraped data is saved in JSON format inside the `Data` directory.

## Requirements

* Python 3.8+
* Chrome browser installed for Selenium automation.
