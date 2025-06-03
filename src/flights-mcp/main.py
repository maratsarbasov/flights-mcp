import hashlib
import os
from typing import Any, Dict, List
import sys
import httpx
import asyncio
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from proposal import *
import json
from cachetools import TTLCache


API_TOKEN: str = os.getenv("FLIGHTS_AVIASALES_API_TOKEN")
MARKER: str = os.getenv("FLIGHTS_AVIASALES_MARKER")
if not API_TOKEN:
    raise ValueError("FLIGHTS_AVIASALES_API_TOKEN environment variable is not set.")
if not MARKER:
    raise ValueError("FLIGHTS_AVIASALES_MARKER environment variable is not set.")

SEARCH_URL = "https://api.travelpayouts.com/v1/flight_search"
RESULTS_URL = "https://api.travelpayouts.com/v1/flight_search_results"

search_results_cache = TTLCache(
    maxsize=10000,  # Maximum number of cached items
    ttl=10 * 60,  # Time to live for each cached item (10 minutes)
)

def _collect_values_sorted(obj: Any) -> List[str]:
    """Return *primitive* values from *obj* following Travelpayouts ordering."""

    if obj is None:
        return []
    if isinstance(obj, (str, int, float, bool)):
        return [str(obj)]
    if isinstance(obj, dict):
        values: List[str] = []
        for key in sorted(obj.keys()):  # alphabetical keys
            values.extend(_collect_values_sorted(obj[key]))
        return values
    if isinstance(obj, (list, tuple)):
        values: List[str] = []
        for item in obj:  # *preserve* list order
            values.extend(_collect_values_sorted(item))
        return values
    # Unsupported types – ignore
    return []


def _generate_signature(token: str, body_without_sig: Dict[str, Any]) -> str:
    """Compute MD5 signature per Travelpayouts Flight Search spec."""

    ordered_values = _collect_values_sorted(body_without_sig)
    base_string = ":".join([token] + ordered_values)
    print(f"Signature base string: {base_string}", file=sys.stderr)
    return hashlib.md5(base_string.encode()).hexdigest()

class SearchRequestSegmentModel(BaseModel):
    origin: str = Field(..., description='Origin IATA (this can be airport IATA or in case city has multiple airports better to use city IATA). The IATA code is shown in uppercase letters LON or MOW')
    destination: str = Field(..., description='Destination IATA (this can be airport IATA or in case city has multiple airports better to use city IATA). The IATA code is shown in uppercase letters LON or MOW')
    date: str = Field(..., description="Departure date in YYYY-MM-DD format")

class SearchRequestModel(BaseModel):
    """Search request model for Travelpayouts Flight Search API."""
    segments: List[SearchRequestSegmentModel] = Field(..., description='''List of CONNECTED flight segments for the same journey. Each segment represents one leg of a multi-city trip or round trip.
        IMPORTANT: Do NOT use multiple segments for alternative dates of the same route. For flexible dates, perform separate searches.
        
        Examples:
        - One way: [{'origin': 'SFO', 'destination': 'LAX', 'date': '2023-10-01'}]
        - Round trip: [{'origin': 'SFO', 'destination': 'LAX', 'date': '2023-10-01'}, {'origin': 'LAX', 'destination': 'SFO', 'date': '2023-10-15'}]
        - Multi-city: [{'origin': 'SFO', 'destination': 'LAX', 'date': '2023-10-01'}, {'origin': 'LAX', 'destination': 'JFK', 'date': '2023-10-05'}]
        
        For alternative dates (e.g., 'July 13 OR July 14'), use separate calls of this tool.''')
    adults: int = Field(1, ge=1, le=9, description="Number of adult passengers (12 years old and older)")
    children: int = Field(0, ge=0, le=6, description="Number of children (2-11 years old)")
    infants: int = Field(0, ge=0, le=6, description="Number of infants (under 2 years old)")
    trip_class: str = Field("Y", description="Trip class - single letter: Y for economy, C for business. Default is Y (economy class)")
    currency: str = Field("USD", description="Currency code (default is USD)")
    locale: str = Field("en", description="Locale for the response (default is en). These are the supported locales: en-us, en-gb, ru, de, es, fr, pl")

mcp = FastMCP("Flights Search", 
              description="This MCP allows you to search for flights using the Aviasales Flight Search API. " \
              "You can specify flight segments, number of passengers, trip class, currency, and locale, apply various filters, and retrieve detailed flight options. " \
              "Typical usage pattern:\n1. search_flights() - Initial broad search (call multiple times if dates are flexible)\n2. get_flight_options() - Filter and sort results (very lightweight tool, call multiple times with different filters)\n3. get_flight_option_details() - Get full details for user's preferred options\n4. request_booking_link() - Only when user confirms booking intent\n\n")

@mcp.tool(
    description="Search for flights using the Aviasales Flight Search API. " \
    "This tool performs search based on the provided flight segments, number of passengers, trip class, currency, and locale. " \
    "It provides search_id and description of search results and saves found options internally." \
    "After receiving the result client can use `get_flight_options` tool to retrieve the found options with more granular filters." \
    "IMPORTANT: All times are local to departure/arrival locations and use HH:MM 24-hour format." \
    "IMPORTANT: Call this tool as many times as needed to find the best flight options."
)
async def search_flights(
    request: SearchRequestModel,
    ctx: Context
) -> Dict[str, Any]:
    """Search for flights using Travelpayouts Flight Search API."""
    
    request_body = request.model_dump()
    request_body["token"] = API_TOKEN
    request_body["marker"] = MARKER
    request_body["passengers"] = {
        "adults": request.adults,
        "children": request.children,
        "infants": request.infants
    }
    del request_body["adults"]
    del request_body["children"]
    del request_body["infants"]

    signature = _generate_signature(API_TOKEN, request_body)
    request_body["signature"] = signature

    async with httpx.AsyncClient(timeout=40) as client:
        init_resp = await client.post(SEARCH_URL, json=request_body)
        if init_resp.status_code != 200:
            raise ToolError(f"Aviasales API returned non-200 status code: {init_resp.status_code}, raw text: {init_resp.text}")
        
        init_data = init_resp.json()
        search_id = init_data["search_id"]
        set_currency_rates(init_data["currency_rates"])

        deadline = datetime.now() + timedelta(seconds=90)  
        batch_proposals = None

        while datetime.now() < deadline:
            await asyncio.sleep(5)
            res_r = await client.get(f"{RESULTS_URL}?uuid={search_id}")
            res_r.raise_for_status()
            res_json = res_r.json()

            # Defensive: ensure we got a *list* per the API spec.
            if not isinstance(res_json, list):
                raise ToolError("Unexpected response format: expected a list of results")

            # Aggregate proposals from every object that contains them.
            for obj in res_json:
                if isinstance(obj, dict) and obj.get("proposals"):
                    try:
                        if not batch_proposals:
                            batch_proposals = parse_proposals_batch(obj)
                        else:
                            batch_proposals = batch_proposals.combine_with(parse_proposals_batch(obj))
                    except Exception as e:
                        print(f"Error parsing proposals: \n {json.dumps(obj, indent=2)}", file=sys.stderr)
                        raise

                    ctx.report_progress(progress=len(batch_proposals.proposals), total=None, message=f"Found {len(batch_proposals.proposals)} options so far...")
                if set(obj.keys()) == {"search_id"}:
                    search_results_cache[search_id] = batch_proposals
                    return batch_proposals.get_description()

        search_results_cache[search_id] = batch_proposals
        return batch_proposals.get_description() if batch_proposals else "No proposals found until the search timed out."

@mcp.tool(
    description="Get flight options from the previously performed search. " \
    "This tool allows you to filter the found flight options by price, departure and arrival times, and airlines. " \
    "It returns a paginated list of flight options that match the specified filters and sorting option." \
    "IMPORTANT: This is very cheap operation, so you can call it as many times as needed to find the best flight options."
)
def get_flight_options(
    search_id: str,
    filters: FiltersModel,
    page: int = Field(0, description="Page number for pagination. Default is 0."),
    page_size: int = Field(10, description="Number of results per page. Default is 10.")
):
    batch = search_results_cache.get(search_id)
    if not batch:
        raise ToolError(f"No search results found for search_id: {search_id}. " \
                        "It may have expired after 10 minutes or not been performed yet. " \
                        "Please perform a search first using the `search_flights` tool.")
    filtered_batch = batch.apply_filters(filters)

    if not filtered_batch.proposals:
        raise ToolError(f"No flight options found for search_id: {search_id} with the specified filters.")
    
    total_results = len(filtered_batch.proposals)
    start_index = page * page_size
    end_index = start_index + page_size
    paginated_results = filtered_batch.proposals[start_index:end_index]
    result = f'Retrieved {len(paginated_results)} flight options for search_id: {search_id} (Page {page}/{(total_results // page_size) + 1})\n\n'

    for i, proposal in enumerate(paginated_results):
        result += proposal.get_short_description()
        if i < len(paginated_results) - 1:
            result += "\n---\n"
    return result
    
@mcp.tool(description="Retrieve detailed information about a specific flight option from the search results. " \
    "This tool provides detailed information about a flight option, including its segments, price, baggage info. " \
    "It is useful for getting more granular information about a specific flight option.")
def get_flight_option_details(
    search_id: str = Field(..., description="Search ID from the previous search_flights tool."),
    offer_id: str = Field(..., description="Offer ID of the flight option for which to request a booking link."),
) -> Dict[str, Any]:
    """Get detailed information about a specific flight option from the search results."""
    
    batch = search_results_cache.get(search_id)
    if not batch:
        raise ToolError(f"No search results found for search_id: {search_id}. " \
                        "It may have expired after 10 minutes. " \
                        "Please perform a search first using the `search_flights` tool.")
    
    proposal = batch.get_proposal_by_id(offer_id)
    if not proposal:
        raise ToolError(f"No flight details found for offer_id: {offer_id} in search_id: {search_id}.")
    
    return proposal.get_full_description()

@mcp.tool(
    description="Request link for booking a flight option. " \
    "This tool generates a booking link for a specific flight option." \
    "This tool is recommended to be used after the user expressed intention to book the flight option." \
)
async def request_booking_link(
    search_id: str = Field(..., description="Search ID from the previous search_flights tool."),
    offer_id: str = Field(..., description="Offer ID of the flight option for which to request a booking link."),
    agency_id: str = Field(..., description="Internal agency ID for generating booking link.")
) -> str:
    """Request a booking link for a specific flight option."""
    
    batch = search_results_cache.get(search_id)
    if not batch:
        raise ToolError(f"No search results found for search_id: {search_id}. " \
                        "It may have expired after 10 minutes. " \
                        "Please perform a search first using the `search_flights` tool.")
    
    proposal = batch.get_proposal_by_id(offer_id)
    if not proposal:
        raise ToolError(f"No flight details found for offer_id: {offer_id} in search_id: {search_id}.")
    
    terms = proposal.terms[agency_id]
    
    get_book_link_api_url = f"https://api.travelpayouts.com/v1/flight_searches/{search_id}/clicks/{terms.url}.json?marker={MARKER}"
    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.get(get_book_link_api_url)
        if response.status_code != 200:
            raise ToolError(f"Aviasales API returned non-200 status code: {response.status_code}", raw_response=response.text)
        data = response.json()
        if not data or "url" not in data:
            raise ToolError("Booking link not found in the response from Aviasales API.")
        book_link = data["url"]
        agency_name = batch.gates_info.get(agency_id).label if batch.gates_info.get(agency_id) else ''
        return f"Booking link on {agency_name}: {book_link}"
    
    return 

if __name__ == "__main__":
    use_streamable_http = os.getenv("FLIGHTS_TRANSPORT", '').lower() == 'streamable_http'
    use_sse = os.getenv("FLIGHTS_TRANSPORT", '').lower() == 'sse'
    if use_streamable_http:
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.getenv("FLIGHTS_HTTP_PORT", 4200)),
            path="/flights",
            log_level="debug",
        )
    elif use_sse:
        mcp.run(
            transport="sse",
            host="0.0.0.0",
            port=int(os.getenv("FLIGHTS_HTTP_PORT", 4200)),
            path="/flights",
            log_level="debug",
        )
    else:
        mcp.run(transport="stdio",
                log_level="debug")

