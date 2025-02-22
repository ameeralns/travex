import os
from dotenv import load_dotenv
import logging
from app.services.pinecone_service import search_places, get_place_details
from app.services.openai_service import process_user_query
from rich.console import Console
from rich.table import Table
from rich import print as rprint
import time
from statistics import mean

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

console = Console()

def format_metadata(metadata):
    """Format metadata for display"""
    return {
        'title': metadata.get('title', 'N/A'),
        'category': metadata.get('category', 'N/A'),
        'rating': float(metadata.get('rating', 0)),
        'reviews': int(metadata.get('reviews', 0)),
        'price_level': metadata.get('price_level', 'N/A'),
        'address': metadata.get('address', 'N/A'),
        'description': metadata.get('description', 'N/A')[:100] + '...' if metadata.get('description') else 'N/A',
        'features': metadata.get('about', 'N/A')[:100] + '...' if metadata.get('about') else 'N/A'
    }

def verify_results(results, expected_category=None, expected_features=None, min_rating=None, price_preference=None):
    """Verify search results meet expected criteria"""
    if not results:
        return False, "No results found"
    
    verifications = []
    
    # Category verification
    if expected_category:
        category_match = any(expected_category.lower() in r.metadata.get('category', '').lower() for r in results)
        verifications.append(('Category', category_match))
    
    # Features verification
    if expected_features:
        feature_matches = []
        for result in results:
            about = result.metadata.get('about', '').lower()
            feature_match = all(feature.lower() in about for feature in expected_features)
            feature_matches.append(feature_match)
        verifications.append(('Features', any(feature_matches)))
    
    # Rating verification
    if min_rating:
        rating_match = all(float(r.metadata.get('rating', 0)) >= min_rating for r in results)
        verifications.append(('Rating', rating_match))
    
    # Price verification
    if price_preference:
        price_matches = []
        for result in results:
            price_level = len(result.metadata.get('price_level', '$').split('$')[0]) + 1
            if price_preference == 'cheap':
                price_matches.append(price_level <= 2)
            elif price_preference == 'moderate':
                price_matches.append(price_level == 2 or price_level == 3)
            elif price_preference == 'expensive':
                price_matches.append(price_level >= 3)
        verifications.append(('Price', any(price_matches)))
    
    # Calculate overall verification score
    success = all(v[1] for v in verifications)
    details = ", ".join([f"{k}: {'✅' if v else '❌'}" for k, v in verifications])
    
    return success, details

def display_results(query, results, verification_details=None):
    """Display search results in a formatted table"""
    console.print(f"\n[bold blue]Results for:[/bold blue] {query}")
    if verification_details:
        console.print(f"[bold yellow]Verification:[/bold yellow] {verification_details}")
    
    if not results:
        console.print("[bold red]No results found![/bold red]")
        return
    
    table = Table(title=f"Search Results")
    
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Title", style="magenta")
    table.add_column("Category", style="blue")
    table.add_column("Rating", justify="right", style="yellow")
    table.add_column("Reviews", justify="right", style="yellow")
    table.add_column("Price", style="green")
    table.add_column("Features", style="white")
    
    for i, result in enumerate(results, 1):
        features = result.metadata.get('about', '')[:50] + '...' if result.metadata.get('about') else 'N/A'
        table.add_row(
            str(i),
            f"{getattr(result, 'combined_score', result.score):.3f}",
            result.metadata.get('title', 'N/A'),
            result.metadata.get('category', 'N/A'),
            f"{float(result.metadata.get('rating', 0)):.1f}",
            str(int(result.metadata.get('reviews', 0))),
            result.metadata.get('price_level', 'N/A'),
            features
        )
    
    console.print(table)
    console.print("\n")

def test_search(query_text, expected_category=None, expected_features=None, min_rating=None, 
                price_preference=None, city="Austin", coordinates=None):
    """Enhanced test search functionality with comprehensive verification"""
    console.print(f"\n[bold blue]Testing Query:[/bold blue] {query_text}")
    
    # Process the query
    query_info = process_user_query(query_text)
    
    # Enhance query info with test parameters
    query_info['location'] = {
        'city': city,
        'coordinates': coordinates
    }
    if price_preference:
        query_info['preferences'] = query_info.get('preferences', {})
        query_info['preferences']['price_level'] = price_preference
    if min_rating:
        query_info['min_rating'] = min_rating
    
    console.print(f"[bold yellow]Processed Query:[/bold yellow]", query_info)
    
    # Test different sorting options
    sort_options = ['best_match', 'rating_high', 'price_low']
    if coordinates:
        sort_options.append('distance')
    
    results_summary = []
    for sort_by in sort_options:
        console.print(f"\n[bold green]Testing sort_by=[/bold green] {sort_by}")
        
        start_time = time.time()
        results = search_places(
            query_info=query_info,
            top_k=5,
            sort_by=sort_by,
            limit=5
        )
        search_time = time.time() - start_time
        
        if results:
            success, verification_details = verify_results(
                results, expected_category, expected_features, min_rating, price_preference
            )
            display_results(query_text, results, verification_details)
            
            results_summary.append({
                'sort_by': sort_by,
                'success': success,
                'time': search_time,
                'results_count': len(results),
                'avg_score': mean(r['score'] for r in results)
            })
        else:
            console.print("[bold red]No results found![/bold red]")
    
    # Display test summary
    if results_summary:
        console.print("\n[bold cyan]Test Summary:[/bold cyan]")
        summary_table = Table(show_header=True)
        summary_table.add_column("Sort By")
        summary_table.add_column("Success")
        summary_table.add_column("Time (s)")
        summary_table.add_column("Results")
        summary_table.add_column("Avg Score")
        
        for summary in results_summary:
            summary_table.add_row(
                summary['sort_by'],
                "✅" if summary['success'] else "❌",
                f"{summary['time']:.3f}",
                str(summary['results_count']),
                f"{summary['avg_score']:.3f}"
            )
        
        console.print(summary_table)
    
    console.print("\n" + "="*80 + "\n")

def test_restaurants():
    """Test restaurant-related queries with enhanced criteria"""
    test_cases = [
        {
            "query": "best Mexican restaurants in Austin",
            "category": "Mexican restaurant",
            "min_rating": 4.0
        },
        {
            "query": "affordable Italian restaurants with outdoor seating",
            "category": "Italian restaurant",
            "features": ["outdoor seating"],
            "price_preference": "cheap"
        },
        {
            "query": "high-end steakhouse with good wine selection",
            "category": "Steakhouse",
            "features": ["wine"],
            "price_preference": "expensive",
            "min_rating": 4.5
        },
        {
            "query": "family-friendly restaurants with playground",
            "features": ["playground", "family"],
            "min_rating": 4.0
        }
    ]
    
    console.print("[bold cyan]Testing Restaurant Queries[/bold cyan]")
    for case in test_cases:
        test_search(
            case["query"],
            expected_category=case.get("category"),
            expected_features=case.get("features"),
            min_rating=case.get("min_rating"),
            price_preference=case.get("price_preference")
        )

def test_location_based():
    """Test location-based queries with coordinates"""
    downtown_austin = (30.2672, -97.7431)
    airport = (30.1975, -97.6664)
    
    test_cases = [
        {
            "query": "restaurants near me",
            "coordinates": downtown_austin,
            "min_rating": 4.0
        },
        {
            "query": "hotels near airport",
            "coordinates": airport,
            "category": "Hotel"
        },
        {
            "query": "coffee shops within walking distance",
            "coordinates": downtown_austin,
            "category": "Coffee shop"
        }
    ]
    
    console.print("[bold cyan]Testing Location-Based Queries[/bold cyan]")
    for case in test_cases:
        test_search(
            case["query"],
            expected_category=case.get("category"),
            min_rating=case.get("min_rating"),
            coordinates=case["coordinates"]
        )

def test_feature_based():
    """Test feature-specific queries"""
    test_cases = [
        {
            "query": "restaurants with vegan options",
            "features": ["vegan"],
            "category": "Restaurant"
        },
        {
            "query": "hotels with swimming pool and gym",
            "features": ["pool", "gym"],
            "category": "Hotel"
        },
        {
            "query": "parks with hiking trails and parking",
            "features": ["hiking", "parking"],
            "category": "Park"
        }
    ]
    
    console.print("[bold cyan]Testing Feature-Based Queries[/bold cyan]")
    for case in test_cases:
        test_search(
            case["query"],
            expected_category=case.get("category"),
            expected_features=case["features"]
        )

def test_price_based():
    """Test price-based queries"""
    test_cases = [
        {
            "query": "cheap eats under $15",
            "price_preference": "cheap",
            "min_rating": 4.0
        },
        {
            "query": "moderate priced Italian restaurants",
            "category": "Italian restaurant",
            "price_preference": "moderate"
        },
        {
            "query": "luxury fine dining experience",
            "price_preference": "expensive",
            "min_rating": 4.5
        }
    ]
    
    console.print("[bold cyan]Testing Price-Based Queries[/bold cyan]")
    for case in test_cases:
        test_search(
            case["query"],
            expected_category=case.get("category"),
            min_rating=case.get("min_rating"),
            price_preference=case["price_preference"]
        )

def main():
    """Run enhanced test suite"""
    console.print("[bold]Starting Enhanced Place Search Testing Suite[/bold]\n")
    
    # Basic category tests
    test_restaurants()
    
    # Location-based tests
    test_location_based()
    
    # Feature-based tests
    test_feature_based()
    
    # Price-based tests
    test_price_based()
    
    console.print("[bold green]Testing Complete![/bold green]")

if __name__ == "__main__":
    main() 