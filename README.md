# Travex - Location Vector Database

A vector database for places and locations, powered by Pinecone and OpenAI embeddings. This project processes location data scraped from Google Maps using [google-maps-scraper](https://github.com/gosom/google-maps-scraper) and creates searchable vector embeddings for use in AI-powered local recommendations and travel assistance.

## Features

- Creates vector embeddings for locations using OpenAI's text-embedding-ada-002 model
- Integrates with google-maps-scraper for data collection
- Stores rich metadata including:
  - Place details (name, category, address)
  - Contact information
  - Ratings and reviews
  - Operating hours
  - Price levels
  - Geographic coordinates
  - Google Maps links
  - Images and thumbnails

## Prerequisites

- Python 3.8+
- OpenAI API key
- Pinecone API key and environment
- [google-maps-scraper](https://github.com/gosom/google-maps-scraper) for data collection
- Scraped location data in CSV format

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd travex
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your API keys:
```env
OPENAI_API_KEY=your_openai_api_key
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_ENVIRONMENT=your_pinecone_environment
PINECONE_INDEX_NAME=your_index_name
```

## Usage

1. First, collect location data using google-maps-scraper:
```bash
# Follow instructions at https://github.com/gosom/google-maps-scraper
```

2. Place your scraped CSV file in the project root as `ScrappedCitycopy.csv`

3. Run the embedding creation script:
```bash
python create_pinecone_embeddings.py
```

The script will:
- Create a Pinecone index if it doesn't exist
- Process the CSV data in batches
- Create embeddings for each location
- Store the embeddings with metadata in Pinecone

## Data Structure

Each vector in the database includes:
- 1536-dimensional embedding of the location description
- Metadata including:
  - Title
  - Category
  - Address
  - Rating and review count
  - Contact information
  - Operating hours
  - Price level
  - Geographic coordinates
  - Links to Google Maps and reviews
  - Thumbnail images

## Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key
- `PINECONE_API_KEY`: Your Pinecone API key
- `PINECONE_ENVIRONMENT`: Pinecone environment (e.g., "us-east-1")
- `PINECONE_INDEX_NAME`: Name of your Pinecone index

## Security

- Never commit the `.env` file
- Keep your API keys secure
- The `.gitignore` file is configured to exclude sensitive data

## License

MIT License

## Contributing

Feel free to submit issues and enhancement requests! 