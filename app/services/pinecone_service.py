from pinecone import Pinecone
import os
from openai import OpenAI
from geopy.distance import geodesic
import logging
import json
from app import get_openai_client, get_pinecone_index

logger = logging.getLogger(__name__)

def create_rich_query_text(query_info):
    """Create a rich search query text from the query info"""
    components = []
    
    # Add the original query
    if 'query_text' in query_info:
        components.append(query_info['query_text'])
    
    # Add location context
    if query_info.get('location', {}).get('city'):
        city = query_info['location']['city']
        state = query_info['location'].get('state', 'Texas')
        components.append(f"in {city}, {state}")
    
    # Add place type
    if query_info.get('place_type'):
        components.append(f"looking for {query_info['place_type']}")
        if query_info.get('sub_type'):
            components.append(f"specifically {query_info['sub_type']}")
    
    # Add preferences
    if query_info.get('preferences'):
        prefs = query_info['preferences']
        if prefs.get('price_level'):
            components.append(f"that is {prefs['price_level']} priced")
        if prefs.get('atmosphere'):
            components.append(f"with {', '.join(prefs['atmosphere'])} atmosphere")
        if prefs.get('features'):
            components.append(f"featuring {', '.join(prefs['features'])}")
    
    return " ".join(components)

def create_query_embedding(query_text):
    """Create embedding for the search query"""
    try:
        logger.debug(f"Creating embedding for query: {query_text}")
        client = get_openai_client()
        
        # Ensure the text is properly formatted
        if not isinstance(query_text, str):
            query_text = str(query_text)
        
        # Create embedding using the latest model
        response = client.embeddings.create(
            input=query_text,
            model="text-embedding-ada-002",
            encoding_format="float"
        )
        
        if not response.data or not response.data[0].embedding:
            raise ValueError("No embedding returned from OpenAI")
            
        embedding = response.data[0].embedding
        logger.debug(f"Successfully created embedding of dimension {len(embedding)}")
        return embedding
        
    except Exception as e:
        logger.error(f"❌ Error creating embedding: {str(e)}")
        logger.exception("Full error traceback:")
        return None

def create_search_filters(query_info):
    """Create Pinecone filters based on query info"""
    filters = {"$and": []}
    
    # Location filter
    if query_info.get('location', {}).get('city'):
        city = query_info['location']['city'].lower()
        location_filter = {
            "$or": [
                {"city": {"$eq": city}},
                {"city": {"$eq": city.title()}},
                {"borough": {"$eq": city}},
                {"borough": {"$eq": city.title()}}
            ]
        }
        filters["$and"].append(location_filter)
    
    # Category/Type filter
    category_terms = []
    if query_info.get('place_type'):
        category_terms.append(query_info['place_type'].lower())
        category_terms.append(query_info['place_type'].title())
    if query_info.get('sub_type'):
        category_terms.append(query_info['sub_type'].lower())
        category_terms.append(query_info['sub_type'].title())
    
    # Add cuisine from preferences
    if query_info.get('preferences', {}).get('cuisine'):
        for cuisine in query_info['preferences']['cuisine']:
            category_terms.append(cuisine.lower())
            category_terms.append(cuisine.title())
    
    if category_terms:
        category_filter = {
            "$or": [{"category": {"$eq": term}} for term in category_terms] +
                  [{"cuisine": {"$eq": term}} for term in category_terms]
        }
        filters["$and"].append(category_filter)
    
    # Price level filter
    if query_info.get('preferences', {}).get('price_level'):
        price_map = {
            'budget': ['$'],
            'moderate': ['$$'],
            'upscale': ['$$$', '$$$$']
        }
        price_level = query_info['preferences']['price_level']
        if price_level in price_map:
            price_filter = {
                "$or": [{"price_level": {"$eq": p}} for p in price_map[price_level]]
            }
            filters["$and"].append(price_filter)
    
    return filters if filters["$and"] else None

def calculate_result_scores(results, query_info):
    """Calculate comprehensive result scores based on multiple factors"""
    for result in results:
        # Base semantic similarity score (0-1)
        semantic_score = result.score
        
        # Rating score (0-1)
        rating = float(result.metadata.get('rating', 0))
        rating_score = rating / 5.0
        
        # Review count score (0-1)
        reviews = int(result.metadata.get('reviews', 0))
        max_reviews = 1000  # Normalize review counts
        review_score = min(reviews / max_reviews, 1.0)
        
        # Price score (0-1)
        price_numeric = int(result.metadata.get('price_numeric', 1))
        price_score = 1 - ((price_numeric - 1) / 3)  # 1=1.0, 2=0.67, 3=0.33, 4=0.0
        
        # Location relevance (0-1)
        location_score = 1.0
        if query_info['location'].get('coordinates'):
            user_coords = query_info['location']['coordinates']
            place_coords = (
                float(result.metadata.get('latitude', 0)),
                float(result.metadata.get('longitude', 0))
            )
            if all(place_coords):
                distance = geodesic(user_coords, place_coords).miles
                location_score = max(0, 1 - (distance / 10))  # Decay over 10 miles
        
        # Feature match score (0-1)
        feature_score = 1.0
        if query_info.get('features'):
            matched_features = sum(1 for f in query_info['features'] 
                                 if f.lower() in result.metadata.get('about', '').lower())
            feature_score = matched_features / len(query_info['features']) if query_info['features'] else 1.0
        
        # Combined weighted score
        result.combined_score = (
            semantic_score * 0.35 +    # Semantic relevance
            rating_score * 0.25 +      # Rating
            review_score * 0.15 +      # Review count
            price_score * 0.10 +       # Price appropriateness
            location_score * 0.10 +    # Location proximity
            feature_score * 0.05       # Feature matches
        )

def search_places(query_info, excluded_places=None, top_k=100):
    """Enhanced semantic search with better filtering and ranking"""
    logger.info("🔎 Starting enhanced search...")
    try:
        # Create rich search text
        search_text = create_rich_query_text(query_info)
        logger.debug(f"Enhanced search text: {search_text}")
        
        # Create embedding
        logger.debug(f"Creating embedding for query: {search_text}")
        embedding = create_query_embedding(search_text)
        if not embedding:
            logger.error("Failed to create embedding")
            return []
            
        logger.debug(f"Successfully created embedding of dimension {len(embedding)}")
        
        # Create filters
        filters = create_search_filters(query_info)
        if filters:
            logger.debug(f"Using filter conditions: {json.dumps(filters, indent=2)}")
        
        # Add excluded places to filter if any
        if excluded_places:
            exclude_filter = {
                "$and": [
                    {"id": {"$nin": list(excluded_places)}}
                ]
            }
            if filters:
                filters["$and"].append(exclude_filter)
            else:
                filters = exclude_filter
        
        # Perform search with filters
        results = get_pinecone_index().query(
            vector=embedding,
            filter=filters,
            top_k=top_k,
            include_metadata=True
        )
        
        if not results.matches and filters:
            logger.warning("No results with filters, trying without...")
            # Try again without category filters but keep location
            if filters.get("$and"):
                location_filter = next((f for f in filters["$and"] if "city" in str(f)), None)
                if location_filter:
                    results = get_pinecone_index().query(
                        vector=embedding,
                        filter={"$and": [location_filter]},
                        top_k=top_k,
                        include_metadata=True
                    )
        
        if not results.matches:
            logger.warning("No results found")
            return []
            
        logger.debug(f"Found {len(results.matches)} matches, returning top 5")
        
        # Enhanced result logging
        for i, match in enumerate(results.matches[:5], 1):
            logger.debug(f"Result {i}: {match.metadata.get('title')} - Score: {match.score:.2f}")
            if 'category' in match.metadata:
                logger.debug(f"Category: {match.metadata['category']}")
            if 'cuisine' in match.metadata:
                logger.debug(f"Cuisine: {match.metadata['cuisine']}")
        
        return results.matches
        
    except Exception as e:
        logger.error(f"❌ Search error: {str(e)}")
        logger.exception("Full error traceback:")
        return []

def get_place_details(place_id):
    """Get detailed information about a specific place"""
    try:
        index = get_pinecone_index()
        response = index.fetch(ids=[place_id])
        
        if not response.vectors:
            return None
            
        place = response.vectors[place_id]
        return place.metadata
        
    except Exception as e:
        logger.error(f"❌ Error fetching place details: {str(e)}")
        return None

def search_by_attribute(query_info, attribute, value):
    """Search for places with specific attributes"""
    try:
        # Convert the attribute search into a rich query
        query_text = f"Looking for places with {attribute} {value}"
        if query_info['location'].get('city'):
            query_text += f" in {query_info['location']['city']}"
        
        # Create embedding
        query_embedding = create_query_embedding(query_text)
        if not query_embedding:
            return []
        
        # Create filters
        filter_conditions = create_search_filters(query_info)
        
        # Add specific attribute filter
        if attribute == 'price':
            if filter_conditions is None:
                filter_conditions = {"$and": []}
            price_value = len(value.split('$'))
            filter_conditions["$and"].append({"price_numeric": {"$eq": price_value}})
        elif attribute == 'rating':
            if filter_conditions is None:
                filter_conditions = {"$and": []}
            filter_conditions["$and"].append({"rating": {"$gte": float(value)}})
        elif attribute == 'features':
            if filter_conditions is None:
                filter_conditions = {"$and": []}
            filter_conditions["$and"].append({"about": {"$contains": value.lower()}})
        
        # Perform search
        search_response = get_pinecone_index().query(
            vector=query_embedding,
            top_k=100,
            include_metadata=True,
            filter=filter_conditions
        )
        
        results = search_response.matches if search_response else []
        
        # Calculate scores and sort
        if results:
            calculate_result_scores(results, query_info)
            results.sort(key=lambda x: x.combined_score, reverse=True)
        
        return results[:5]  # Return top 5 results
        
    except Exception as e:
        logger.error(f"❌ Error in attribute search: {str(e)}")
        logger.exception("Full error traceback:")
        return [] 