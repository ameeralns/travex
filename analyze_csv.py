import pandas as pd
import json
from collections import Counter
import logging
from rich.console import Console
from rich.table import Table

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

console = Console()

def analyze_csv_structure():
    """Analyze the structure and content of the CSV file"""
    try:
        # Read the CSV file
        df = pd.read_csv('ScrappedCitycopy.csv')
        
        # Basic dataset information
        console.print("\n[bold cyan]Dataset Overview:[/bold cyan]")
        console.print(f"Total number of records: {len(df)}")
        console.print(f"Number of columns: {len(df.columns)}")
        
        # Column analysis
        console.print("\n[bold cyan]Column Analysis:[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Column Name")
        table.add_column("Non-Null Count")
        table.add_column("Data Type")
        table.add_column("Sample Values")
        
        for column in df.columns:
            non_null_count = df[column].count()
            dtype = str(df[column].dtype)
            sample = str(df[column].dropna().head(2).tolist())[:50] + "..."
            table.add_row(column, str(non_null_count), dtype, sample)
        
        console.print(table)
        
        # Category analysis
        if 'category' in df.columns:
            console.print("\n[bold cyan]Category Distribution:[/bold cyan]")
            category_counts = df['category'].value_counts().head(10)
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Category")
            table.add_column("Count")
            
            for cat, count in category_counts.items():
                table.add_row(str(cat), str(count))
            
            console.print(table)
        
        # Location analysis
        if 'address' in df.columns:
            console.print("\n[bold cyan]Location Analysis:[/bold cyan]")
            # Extract city from address if possible
            df['city'] = df['address'].str.extract(r'([^,]+),\s*TX')
            city_counts = df['city'].value_counts().head(5)
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("City")
            table.add_column("Count")
            
            for city, count in city_counts.items():
                table.add_row(str(city), str(count))
            
            console.print(table)
        
        # Rating analysis
        if 'review_rating' in df.columns:
            console.print("\n[bold cyan]Rating Distribution:[/bold cyan]")
            rating_stats = df['review_rating'].describe()
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Statistic")
            table.add_column("Value")
            
            for stat, value in rating_stats.items():
                table.add_row(str(stat), f"{value:.2f}")
            
            console.print(table)
        
        # Check for potential embedding-relevant fields
        console.print("\n[bold cyan]Fields for Embedding Enhancement:[/bold cyan]")
        embedding_fields = ['title', 'category', 'descriptions', 'about', 'features', 'price_range']
        available_fields = [field for field in embedding_fields if field in df.columns]
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Field")
        table.add_column("Availability")
        table.add_column("Non-Null %")
        
        for field in embedding_fields:
            if field in df.columns:
                non_null_pct = (df[field].count() / len(df)) * 100
                table.add_row(field, "✅", f"{non_null_pct:.1f}%")
            else:
                table.add_row(field, "❌", "0%")
        
        console.print(table)
        
    except Exception as e:
        logger.error(f"Error analyzing CSV: {str(e)}")
        raise

if __name__ == "__main__":
    analyze_csv_structure() 