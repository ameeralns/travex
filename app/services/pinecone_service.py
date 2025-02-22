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
    
    # Add the original query with high importance
    if 'query_text' in query_info:
        components.append(query_info['query_text'])
    
    # Add location context
    if query_info.get('location', {}).get('city'):
        city = query_info['location']['city']
        state = query_info['location'].get('state', 'Texas')
        components.append(f"in {city}, {state}")
    
    # Add place type with variations
    if query_info.get('place_type') and query_info['place_type'] != 'place':
        place_type = query_info['place_type']
        if place_type == 'restaurant':
            # Extract cuisine type from original query if present
            query_lower = query_info['query_text'].lower()
            cuisine_types = ['mexican', 'italian', 'chinese', 'japanese', 'thai', 'indian', 'bbq', 'american']
            found_cuisine = next((cuisine for cuisine in cuisine_types if cuisine in query_lower), None)
            if found_cuisine:
                components.append(f"looking for {found_cuisine} restaurants, {found_cuisine} food, {found_cuisine} cuisine")
            components.append("restaurant, place to eat, dining establishment")
        elif place_type == 'outdoor':
            components.append("trail, park, hiking trail, outdoor recreation, nature area, garden")
        elif place_type == 'hotel':
            components.append("hotel, motel, place to stay, accommodation, lodging")
        else:
            components.append(f"looking for {place_type}")
    
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
    """Create enhanced Pinecone filters based on query info"""
    filters = {"$and": []}
    
    # Location filter with variations
    if query_info.get('location', {}).get('city'):
        city = query_info['location']['city']
        location_filter = {
            "$or": [
                {"city": {"$eq": city.lower()}},
                {"city": {"$eq": city.title()}},
                {"city": {"$eq": city.upper()}},
                {"borough": {"$eq": city.lower()}},
                {"borough": {"$eq": city.title()}},
                {"borough": {"$eq": city.upper()}}
            ]
        }
        filters["$and"].append(location_filter)
    
    # Enhanced place type and cuisine filter
    if query_info.get('place_type'):
        place_type = query_info['place_type'].lower()
        
        # Check for cuisine type in the original query
        query_lower = query_info['query_text'].lower()
        cuisine_types = {
            'mexican': ['mexican restaurant', 'mexican food', 'mexican cuisine', 'taqueria', 'tex-mex'],
            'italian': ['italian restaurant', 'italian food', 'italian cuisine', 'pizzeria', 'trattoria'],
            'chinese': ['chinese restaurant', 'chinese food', 'chinese cuisine', 'dim sum'],
            'japanese': ['japanese restaurant', 'japanese food', 'sushi', 'ramen'],
            'thai': ['thai restaurant', 'thai food', 'thai cuisine'],
            'indian': ['indian restaurant', 'indian food', 'indian cuisine'],
            'bbq': ['bbq', 'barbecue', 'smokehouse', 'grill'],
            'american': ['american restaurant', 'american food', 'diner', 'grill']
        }
        
        # Detect cuisine type
        detected_cuisine = None
        for cuisine, keywords in cuisine_types.items():
            if any(keyword in query_lower for keyword in keywords):
                detected_cuisine = cuisine
                break
        
        if detected_cuisine:
            # Add specific cuisine type filter
            cuisine_filter = {
                "$or": [
                    {"cuisine_type": {"$eq": detected_cuisine.lower()}},
                    {"cuisine_type": {"$eq": detected_cuisine.title()}},
                    {"category": {"$eq": f"{detected_cuisine.title()} Restaurant"}},
                    {"category": {"$eq": f"{detected_cuisine.lower()} restaurant"}},
                    {"features": {"$in": [detected_cuisine.lower(), detected_cuisine.title()]}},
                    {"about": {"$contains": detected_cuisine.lower()}}
                ]
            }
            filters["$and"].append(cuisine_filter)
        else:
            # General restaurant category if no specific cuisine
            category_variations = {
                'restaurant': ['Restaurant', 'restaurant', 'Eatery', 'eatery', 'Dining', 'dining'],
                'bar': ['Bar', 'bar', 'Pub', 'pub', 'Lounge', 'lounge'],
                'cafe': ['Cafe', 'cafe', 'Coffee Shop', 'coffee shop'],
                'outdoor': ['Trail', 'trail', 'Park', 'park', 'Garden', 'garden'],
                'hotel': ['Hotel', 'hotel', 'Motel', 'motel', 'Lodging', 'lodging'],
                'shopping': ['Store', 'store', 'Shop', 'shop', 'Mall', 'mall']
            }
            
            if place_type in category_variations:
                type_filter = {
                    "$or": [
                        {"category": {"$eq": variation}} for variation in category_variations[place_type]
                    ]
                }
                filters["$and"].append(type_filter)
    
    # Rating filter if specified
    if query_info.get('min_rating'):
        filters["$and"].append({
            "rating": {"$gte": float(query_info['min_rating'])}
        })
    
    # Price level filter if specified
    if query_info.get('preferences', {}).get('price_level'):
        price_map = {
            'budget': ['$', '$$'],
            'moderate': ['$$', '$$$'],
            'upscale': ['$$$', '$$$$']
        }
        price_level = query_info['preferences']['price_level']
        if price_level in price_map:
            price_filter = {
                "$or": [{"price_level": {"$eq": p}} for p in price_map[price_level]]
            }
            filters["$and"].append(price_filter)
    
    # Exclude specific IDs if provided
    if query_info.get('excluded_ids'):
        filters["$and"].append({
            "id": {"$nin": list(query_info['excluded_ids'])}
        })
    
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

def search_places(query_info, top_k=5, excluded_ids=None, sort_by='best_match', limit=None):
    """Enhanced semantic search with better filtering and ranking"""
    try:
        # Add excluded IDs to query info
        if excluded_ids:
            query_info['excluded_ids'] = excluded_ids
        
        # Create rich search text
        rich_query = create_rich_query_text(query_info)
        logger.info(f"🔍 Rich query: {rich_query}")
        
        # Generate embedding
        query_embedding = create_query_embedding(rich_query)
        if not query_embedding:
            logger.error("Failed to create query embedding")
            return []
        
        # Create filters
        filters = create_search_filters(query_info)
        logger.info(f"🎯 Search filters: {json.dumps(filters, indent=2)}")
        
        # Perform search with relaxed filters first
        try:
            results = get_pinecone_index().query(
                vector=query_embedding,
                top_k=top_k * 2,  # Get more results for better post-processing
                filter=filters,
                include_metadata=True
            )
            
            if results and results.matches:
                logger.info(f"Found {len(results.matches)} results with filters")
                return process_search_results(results.matches, query_info, sort_by, limit)
                
        except Exception as e:
            logger.error(f"Error in initial Pinecone search: {str(e)}")
        
        # If no results or error, try without category filters
        logger.info("Trying search without category filters...")
        basic_filters = {"$and": []} if not filters else {"$and": [f for f in filters["$and"] if "category" not in str(f)]}
        
        try:
            results = get_pinecone_index().query(
                vector=query_embedding,
                top_k=top_k * 2,
                filter=basic_filters if basic_filters["$and"] else None,
                include_metadata=True
            )
            
            if results and results.matches:
                logger.info(f"Found {len(results.matches)} results with relaxed filters")
                return process_search_results(results.matches, query_info, sort_by, limit)
                
        except Exception as e:
            logger.error(f"Error in relaxed Pinecone search: {str(e)}")
        
        # If still no results, try with just location filter
        logger.info("Trying search with only location filter...")
        location_filter = None
        if filters and filters["$and"]:
            location_filters = [f for f in filters["$and"] if "city" in str(f) or "borough" in str(f)]
            if location_filters:
                location_filter = {"$and": location_filters}
        
        try:
            results = get_pinecone_index().query(
                vector=query_embedding,
                top_k=top_k * 2,
                filter=location_filter,
                include_metadata=True
            )
            
            if results and results.matches:
                logger.info(f"Found {len(results.matches)} results with location filter only")
                return process_search_results(results.matches, query_info, sort_by, limit)
                
        except Exception as e:
            logger.error(f"Error in location-only Pinecone search: {str(e)}")
        
        return []
        
    except Exception as e:
        logger.error(f"Error in search_places: {str(e)}")
        logger.exception("Full error traceback:")
        return []

def process_search_results(matches, query_info, sort_by='best_match', limit=None):
    """
    Process and rank search results
    
    Args:
        matches: Raw search matches from Pinecone
        query_info (dict): Original query information
        sort_by (str): Sorting method ('best_match', 'rating_high', 'price_low', 'distance')
        limit (int): Optional limit on number of results
        
    Returns:
        list: Processed and sorted results
    """
    try:
        processed_results = []
        for match in matches:
            # Calculate comprehensive score
            base_score = match.score
            
            # Adjust score based on rating if available
            rating_boost = 0
            if match.metadata.get('rating'):
                try:
                    rating = float(match.metadata['rating'])
                    rating_boost = (rating - 3.5) / 5.0  # Normalize rating boost
                except (ValueError, TypeError):
                    pass
                    
            # Adjust score based on review count if available
            review_boost = 0
            if match.metadata.get('review_count'):
                try:
                    review_count = int(match.metadata['review_count'])
                    review_boost = min(review_count / 1000, 0.2)  # Cap at 0.2
                except (ValueError, TypeError):
                    pass
                    
            # Preference matching boost
            preference_boost = 0
            preferences = query_info.get('preferences', {})
            
            # Check price level match
            if preferences.get('price_level') and match.metadata.get('price_level') == preferences['price_level']:
                preference_boost += 0.1
                
            # Check atmosphere match
            if preferences.get('atmosphere') and match.metadata.get('atmosphere'):
                user_atmosphere = set(preferences['atmosphere'])
                place_atmosphere = set(match.metadata['atmosphere'])
                atmosphere_match = len(user_atmosphere.intersection(place_atmosphere))
                preference_boost += atmosphere_match * 0.05
                
            # Calculate final score
            final_score = base_score + rating_boost + review_boost + preference_boost
            
            # Calculate distance if coordinates are provided
            distance = None
            if query_info.get('location', {}).get('coordinates'):
                try:
                    user_coords = query_info['location']['coordinates']
                    place_coords = (
                        float(match.metadata.get('latitude', 0)),
                        float(match.metadata.get('longitude', 0))
                    )
                    if all(place_coords):
                        distance = geodesic(user_coords, place_coords).miles
                except (ValueError, TypeError):
                    pass
            
            # Add processed result
            processed_result = {
                'id': match.id,
                'score': final_score,
                'metadata': match.metadata,
                'base_score': base_score,
                'rating_boost': rating_boost,
                'review_boost': review_boost,
                'preference_boost': preference_boost
            }
            
            # Add distance if calculated
            if distance is not None:
                processed_result['distance'] = distance
                
            processed_results.append(processed_result)
            
        # Apply sorting based on sort_by parameter
        if sort_by == 'rating_high':
            processed_results.sort(
                key=lambda x: (
                    float(x['metadata'].get('rating', 0)),
                    x['score']
                ),
                reverse=True
            )
        elif sort_by == 'price_low':
            processed_results.sort(
                key=lambda x: (
                    len(x['metadata'].get('price_level', '$')),
                    -x['score']
                )
            )
        elif sort_by == 'distance' and any('distance' in r for r in processed_results):
            processed_results.sort(
                key=lambda x: (
                    x.get('distance', float('inf')),
                    -x['score']
                )
            )
        else:  # 'best_match' or default
            processed_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Apply limit if specified
        if limit is not None:
            processed_results = processed_results[:limit]
        
        # Log top matches
        logger.info(f"Top matches: {[{r['metadata']['title']: r['score']} for r in processed_results[:3]]}")
        
        return processed_results
        
    except Exception as e:
        logger.error(f"Error processing search results: {str(e)}")
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