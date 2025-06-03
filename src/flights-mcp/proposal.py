from datetime import datetime, time
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self
from enum import Enum

currency_rates: Dict[str, float] = {}
def set_currency_rates(rates: Dict[str, float]) -> None:
    global currency_rates
    currency_rates = rates
def get_currency_rate(currency: str) -> float:
    if currency not in currency_rates:
        raise ValueError(f"Currency rate for {currency} not found in price rates.")
    return currency_rates[currency]

def convert_unified_price_to_user(unified_price: int, currency: str) -> int:
    user_currency_rate = get_currency_rate(currency)
    if user_currency_rate is None:
        raise ValueError(f"Currency rate for {currency} not found in price rates.")
    return int(unified_price / user_currency_rate)

def convert_user_price_to_unified(user_price: int, currency: str) -> int:
    user_currency_rate = get_currency_rate(currency)
    if user_currency_rate is None:
        raise ValueError(f"Currency rate for {currency} not found in price rates.")
    return int(user_price * user_currency_rate)

def format_duration(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}h {mins:02d}m"

class SortingMethod(str, Enum):
    CHEAP_FIRST = "cheap_first"
    EARLY_DEPARTURE_FIRST = "early_departure_first"
    EARLY_ARRIVAL_FIRST = "early_arrival_first"
    MINIMAL_DURATION_FIRST = "minimal_duration_first"


class TimeRange(BaseModel):
    """Time range for filtering departure/arrival times"""
    start_time: Optional[str] = Field(None, description="Start time in HH:MM format (e.g., '08:00')")
    end_time: Optional[str] = Field(None, description="End time in HH:MM format (e.g., '22:00')")
    
    @field_validator('start_time', 'end_time')
    def validate_time_format(cls, v):
        if v is None:
            return v
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError(f"Time must be in HH:MM format, got: {v}")


class SegmentTimeFilter(BaseModel):
    """Time filters for a specific segment"""
    departure_time_range: Optional[TimeRange] = None
    arrival_time_range: Optional[TimeRange] = None


class FiltersModel(BaseModel):
    """Model for filtering flight proposals"""
    max_total_duration: Optional[int] = Field(None, description="Maximum total duration of whole trip in minutes")
    max_price: Optional[int] = Field(None, description="Maximum price filter")
    allowed_airlines: Optional[List[str]] = Field(None, description="List of allowed airline IATA codes")
    segment_time_filters: Optional[List[SegmentTimeFilter]] = Field(None, description="Time filters for each segment")
    max_stops: Optional[int] = Field(None, description="Maximum number of stops allowed")
    sorting: Optional[SortingMethod] = Field(SortingMethod.CHEAP_FIRST, description="Sorting method")


class TransferTerms(BaseModel):
    is_virtual_interline: bool

class FlightAdditionalTariffInfo(BaseModel):
    return_before_flight:  Optional[bool] = None
    return_after_flight:   Optional[bool] = None
    change_before_flight:  Optional[bool] = None
    change_after_flight:   Optional[bool] = None

    @field_validator('*', mode='before')
    def extract_available(cls, value):
        if isinstance(value, dict):
            return value.get('available')
        return value


class Flight(BaseModel):
    aircraft: Optional[str] = None
    arrival: str
    arrival_date: str
    arrival_time: str
    arrival_timestamp: int
    delay: int
    departure: str
    departure_date: str
    departure_time: str
    departure_timestamp: int
    duration: int
    equipment: Optional[str] = None
    local_arrival_timestamp: int
    local_departure_timestamp: int
    marketing_carrier: Optional[str] = None
    number: str
    operating_carrier: str
    operated_by: str
    rating: Optional[int]
    technical_stops: Optional[Any]
    trip_class: str
    # Baggage and tariff info moved from Terms to Flight level
    # baggage: Union[bool, str] = Field(description="Baggage allowance for this flight")
    # handbag: Union[bool, str] = Field(description="Handbag allowance for this flight")
    # additional_tariff_info: Optional[FlightAdditionalTariffInfo] = Field(description="Tariff information for this flight")
    # baggage_source: int = Field(description="Source of baggage information")
    # handbag_source: int = Field(description="Source of handbag information")

    def get_full_flight_number(self) -> str:
        if self.marketing_carrier is not None:
            return f"{self.marketing_carrier} {self.number}"
        return f"{self.operating_carrier} {self.number}"

class Terms(BaseModel):
    currency: str
    price: int
    unified_price: int
    url: int
    transfer_terms: List[List[TransferTerms]]
    flights_baggage: List[List[Union[bool, str]]]
    flights_handbags: List[List[Union[bool, str]]]
    # Removed flights_baggage, flights_handbags, flight_additional_tariff_infos
    # as they are now part of Flight model


class SegmentRating(BaseModel):
    total: float


class VisaRules(BaseModel):
    required: bool


class Duration(BaseModel):
    seconds: int


class Transfer(BaseModel):
    at: str
    to: str
    airports: List[str]
    airlines: List[str]
    country_code: str
    city_code: str
    visa_rules: VisaRules
    night_transfer: bool
    tags: Optional[List[str]] = None
    duration_seconds: int
    duration: Duration


class Segment(BaseModel):
    flight: List[Flight]
    rating: Optional[SegmentRating] = None
    transfers: Optional[List[Transfer]] = None

    @model_validator(mode='after')
    def check_passwords_match(self) -> Self:
        if len(self.flight) > 1:
            if not self.transfers:
                raise ValueError("Transfers must be provided for segments with multiple flights")
        return self

class Proposal(BaseModel):
    terms: Dict[str, Terms]
    xterms: Dict[str, Dict[str, Terms]]
    segment: List[Segment]
    total_duration: int
    stops_airports: List[str]
    is_charter: bool
    max_stops: int
    max_stop_duration: Optional[int] = None
    min_stop_duration: Optional[int] = None
    carriers: List[str]
    segment_durations: List[int]
    segments_time: List[List[int]]
    segments_airports: List[List[str]]
    sign: str
    is_direct: bool
    flight_weight: float
    popularity: int
    segments_rating: Optional[float] = None
    tags: Optional[List[str]] = None
    validating_carrier: str

    batch_ref: 'ProposalsBatchModel' = Field(default=None, exclude=True)

    def merge_terms(self, other: 'Proposal') -> None:
        """
        Merge terms from another Proposal into this one.
        
        Args:
            other: Another Proposal instance to merge terms from
        """
        for gate_id, terms in other.terms.items():
            if gate_id not in self.terms:
                self.terms[gate_id] = terms
            else:
                pass  # If terms already exist, we assume they are the same and do not merge
        
        # Merge xterms similarly if needed
        for gate_id, xterms in other.xterms.items():
            if gate_id not in self.xterms:
                self.xterms[gate_id] = xterms
            else:
                pass  # If terms already exist, we assume they are the same and do not merge

    def get_cheapest_unified_price(self) -> int:
        """
        Get the cheapest price and currency from all available terms.
        
        Returns:
            Tuple of (price, currency)
        """
        min_unified_price = float('inf')
        
        for gate_id, terms in self.terms.items():
            if terms.unified_price < min_unified_price:
                min_unified_price = terms.unified_price
        
        return int(min_unified_price)

    def get_earliest_departure_time(self) -> datetime:
        """Get the earliest departure time across all segments"""
        earliest_timestamp = min(
            flight.departure_timestamp 
            for segment in self.segment 
            for flight in segment.flight
        )
        return datetime.fromtimestamp(earliest_timestamp)

    def get_latest_arrival_time(self) -> datetime:
        """Get the latest arrival time across all segments"""
        latest_timestamp = max(
            flight.arrival_timestamp 
            for segment in self.segment 
            for flight in segment.flight
        )
        return datetime.fromtimestamp(latest_timestamp)
    
    def get_short_description(self, include_cheapest_price: bool = True, include_aircraft: bool = False) -> str:
        """
        Generate a short description of the proposal.
        
        Returns:
            A string summarizing the proposal
        """
        cheapest_price = self.get_cheapest_unified_price()
        formatted_price = f"{convert_unified_price_to_user(cheapest_price, self.batch_ref.currency)} {self.batch_ref.currency.upper()}"
        
        description_parts = []
        description_parts.append(f"* **Offer ID**: {self.sign}")
        if include_cheapest_price:
            description_parts.append(f"* **Price**: {formatted_price}")
        for segment in self.segment:
            layover_count = len(segment.transfers) if segment.transfers else 0
            layovers_text = f"{layover_count} layover{'s' if layover_count != 1 else ''}" if layover_count > 0 else "direct flight"
            description_parts.append(f"* From {segment.flight[0].departure} to {segment.flight[-1].arrival} ({layovers_text})")
        
            for i, flight in enumerate(segment.flight):
                departure_airport = self.batch_ref.airports.get(flight.departure, flight.departure)
                arrival_airport = self.batch_ref.airports.get(flight.arrival, flight.arrival)
                airline_name = self.batch_ref.airlines.get(flight.operating_carrier).name if flight.operating_carrier in self.batch_ref.airlines else flight.operating_carrier
                aircraft_name = f", aircraft: {flight.aircraft}" if include_aircraft and flight.aircraft else ''
                description_parts.append(f"  * From {departure_airport.name} ({flight.departure}) on {flight.departure_date} at {flight.departure_time} -> " \
                                         f"to {arrival_airport.name} ({flight.arrival}) on {flight.arrival_date} at {flight.arrival_time} " \
                                         f"(duration: {format_duration(flight.duration)}), flight number: {flight.get_full_flight_number()}{aircraft_name}, operated by {airline_name})")
                
        
                transfer = segment.transfers[i] if segment.transfers and i < len(segment.transfers) else None
                if transfer:
                    if transfer.at != transfer.to:
                        description_parts.append(f"    * Airport change from {transfer.at} to {transfer.to}")
                    else:
                        transfer_duration = f'{transfer.duration_seconds // 60 // 60}h {transfer.duration_seconds // 60 % 60}m'
                        description_parts.append(f"    * Layover at {transfer.at} for {transfer_duration}")

        description_parts.append(f"* Total Duration: {format_duration(self.total_duration)}")
        return "\n".join(description_parts)
    
    def get_full_description(self) -> str:
        description_parts = [self.get_short_description(include_cheapest_price=False, include_aircraft=True)]
        if self.is_charter:
            description_parts.append("* This is a charter flight.")
        description_parts.append(f"* This ticket is offered by {len(self.terms)} agencies with the following terms:")
        for term_id, terms in self.terms.items():
            agency = self.batch_ref.gates_info.get(term_id)
            if agency:
                description_parts.append(f"* Agency {agency.label} (internal agency ID: {term_id})")
            else:
                description_parts.append(f"* Agency (internal agency ID: {term_id})")
            description_parts.append(f"  * **Price:** {terms.price} {terms.currency.upper()} " \
                                     f"(in user currency: {convert_unified_price_to_user(terms.unified_price, self.batch_ref.currency)} {self.batch_ref.currency.upper()})")
            
            description_parts.append(f"  * Baggage info:")
            for segment_idx, segment in enumerate(self.segment):
                for flight_idx, flight in enumerate(segment.flight):
                    baggage = terms.flights_baggage[segment_idx][flight_idx]

                    handbag = terms.flights_handbags[segment_idx][flight_idx]
                    description_parts.append(f"    * Flight {flight.get_full_flight_number()}: \n" \
                                             f"      * {parse_baggage_string(baggage)} \n" \
                                             f"      * {parse_carry_on_string(handbag)}")
        if self.tags:
            description_parts.append(f"* Tags: {', '.join(self.tags)}")
        
        return "\n".join(description_parts)
            
def parse_baggage_string(baggage_str: bool | str, ) -> Union[bool, str]:
    """    
    "" — there is no information about baggage
    false — baggage is not included in the price
    0PC — without baggage
    {int}PC{int} — number of bags by %somevalue% kilogram. For example, 2PC23 — means two baggage pieces of 23 kg 
    {int}PC - number of bags without weight information. For example, 1PC means one piece of luggage.
    {int} — number of bags does not matter, the total weight is limited
    """
    if isinstance(baggage_str, bool) and baggage_str == False:
        return "Baggage is not included in the price"
    elif baggage_str == '':
        return "No baggage information available"
    elif baggage_str == "0PC":
        return "Baggage is not included in the price"
    elif "PC" in baggage_str:
        parts = baggage_str.split("PC")
        if parts[0].isdigit():
            return f"{parts[0]} piece(s) of baggage"
        else:
            return "no baggage information"
    return "no baggage information"

def parse_carry_on_string(baggage_str: bool | str, ) -> Union[bool, str]:
    """    
    "" — there is no information about baggage
    false — baggage is not included in the price
    0PC — without baggage
    {int}PC{int} — number of bags by %somevalue% kilogram. For example, 2PC23 — means two baggage pieces of 23 kg 
    {int}PC - number of bags without weight information. For example, 1PC means one piece of luggage.
    {int} — number of bags does not matter, the total weight is limited
    """
    if isinstance(baggage_str, bool) and baggage_str == False:
        return "Carry-on piece is not included in the price"
    elif baggage_str == '':
        return "No Carry-on piece information available"
    elif baggage_str == "0PC":
        return "Carry-on piece is not included in the price"
    elif "PC" in baggage_str:
        parts = baggage_str.split("PC")
        if parts[0].isdigit():
            return f"{parts[0]} piece(s) of carry-on piece"
        else:
            return "no carry-on piece information"
    return "no Carry-on piece information"

class Coordinates(BaseModel):
    lat: float
    lon: float


class Airport(BaseModel):
    name: str
    city: str
    city_code: str
    country: str
    country_code: str
    time_zone: str
    coordinates: Coordinates


class GateError(BaseModel):
    code: int
    tos: str


class Gate(BaseModel):
    count: int
    good_count: int
    bad_count: Dict[str, Any]
    duration: float
    id: int
    gate_label: str
    merged_codeshares: int
    error: GateError
    created_at: int
    server_name: str
    cache: bool
    cache_search_uuid: str


class Meta(BaseModel):
    uuid: str
    gates: List[Gate]


class Airline(BaseModel):
    id: Optional[int] = None
    iata: str
    lowcost: Optional[bool] = False
    average_rate: Optional[float] = None
    rates: Optional[int] = None
    name: Optional[str] = None
    brand_color: Optional[str] = None


class GateInfo(BaseModel):
    id: int
    label: str
    payment_methods: List[str]
    mobile_version: Optional[bool] = None
    productivity: int
    currency_code: str


class SegmentInfo(BaseModel):
    origin: str
    origin_country: str
    original_origin: str
    destination: str
    destination_country: str
    original_destination: str
    date: str
    depart_date: str


class ProposalsBatchModel(BaseModel):
    proposals: List[Proposal]
    airports: Dict[str, Airport]
    search_id: str
    chunk_id: str
    meta: Meta
    airlines: Dict[str, Airline]
    gates_info: Dict[str, GateInfo]
    flight_info: Dict[str, Any]
    segments: List[SegmentInfo]
    market: str
    clean_marker: str
    open_jaw: bool
    currency: str
    initiated_at: str

    def combine_with(self, other: 'ProposalsBatchModel') -> 'ProposalsBatchModel':
        """
        Combine this batch with another batch of proposals.
        
        Args:
            other: Another ProposalsBatchModel to combine with this one
            
        Returns:
            A new ProposalsBatchModel with combined data
        """
        # Combine proposals

        combined_proposals = self.proposals.copy()
        
        for pi2, p2 in enumerate(other.proposals):
            exists = False
            for pi1, p1 in enumerate(self.proposals):
                if p1.sign == p2.sign:
                    combined_proposals[pi1].merge_terms(p2)
                    exists = True
            if not exists:
                combined_proposals.append(p2)            
        
        # Combine airports (merge dictionaries, other takes precedence for conflicts)
        combined_airports = {**self.airports, **other.airports}
        
        # Combine airlines (merge dictionaries, other takes precedence for conflicts)
        combined_airlines = {**self.airlines, **other.airlines}
        
        # Combine gates_info (merge dictionaries, other takes precedence for conflicts)
        combined_gates_info = {**self.gates_info, **other.gates_info}
        
        # Combine flight_info (merge dictionaries, other takes precedence for conflicts)
        combined_flight_info = {**self.flight_info, **other.flight_info}
        
        # Combine gates in meta
        combined_gates = self.meta.gates + other.meta.gates
        combined_meta = Meta(
            uuid=other.meta.uuid,  # Use the latest UUID
            gates=combined_gates
        )
        
        if self.segments != other.segments:
            raise ValueError("Segments in both batches must be identical to combine them.")
        
        return ProposalsBatchModel(
            proposals=combined_proposals,
            airports=combined_airports,
            search_id=other.search_id,  # Use the latest search_id
            chunk_id=other.chunk_id,   # Use the latest chunk_id
            meta=combined_meta,
            airlines=combined_airlines,
            gates_info=combined_gates_info,
            flight_info=combined_flight_info,
            segments=other.segments,  # Use the latest segments
            market=other.market,  # Use the latest market
            clean_marker=other.clean_marker,  # Use the latest clean_marker
            open_jaw=other.open_jaw,  # Use the latest open_jaw
            currency=other.currency,  # Use the latest currency
            initiated_at=other.initiated_at  # Use the latest initiated_at
        )
    
    def get_proposal_by_id(self, proposal_id: str) -> Optional[Proposal]:
        for proposal in self.proposals:
            if proposal.sign == proposal_id:
                return proposal
        return None
    
    def apply_filters(self, filters: FiltersModel) -> 'ProposalsBatchModel':
        """
        Apply filters to the proposals and return a new ProposalsBatchModel with filtered results.
        
        Args:
            filters: FiltersModel containing all filter criteria
            
        Returns:
            New ProposalsBatchModel with filtered proposals
        """
        filtered_proposals = []
        
        for proposal in self.proposals:
            if self._proposal_matches_filters(proposal, filters):
                filtered_proposals.append(proposal)
        
        # Apply sorting
        if filters.sorting:
            filtered_proposals = self._sort_proposals(filtered_proposals, filters.sorting)
        
        # Create new instance with filtered proposals
        return ProposalsBatchModel(
            proposals=filtered_proposals,
            airports=self.airports,
            search_id=self.search_id,
            chunk_id=self.chunk_id,
            meta=self.meta,
            airlines=self.airlines,
            gates_info=self.gates_info,
            flight_info=self.flight_info,
            segments=self.segments,
            market=self.market,
            clean_marker=self.clean_marker,
            open_jaw=self.open_jaw,
            currency=self.currency,
            initiated_at=self.initiated_at
        )
    
    def _proposal_matches_filters(self, proposal: Proposal, filters: FiltersModel) -> bool:
        """Check if a proposal matches all filter criteria"""
        
        # Duration filter
        if filters.max_total_duration is not None:
            if proposal.total_duration > filters.max_total_duration:
                return False
        
        # Price filter
        if filters.max_price is not None:
            price = proposal.get_cheapest_unified_price()
            if filters.max_price is not None and convert_unified_price_to_user(price, self.currency) > filters.max_price:
                return False
        
        # Airlines filter
        if filters.allowed_airlines is not None:
            # Check if any of the proposal's carriers are in the allowed list
            allowed_set = set(filters.allowed_airlines)
            proposal_carriers = set(proposal.carriers)
            if not proposal_carriers.intersection(allowed_set):
                return False
        
        # Stops filter
        if filters.max_stops is not None:
            if proposal.max_stops > filters.max_stops:
                return False
        
        # Segment time filters
        if filters.segment_time_filters is not None:
            for seg_idx, segment in enumerate(proposal.segment):
                if seg_idx < len(filters.segment_time_filters):
                    seg_filter = filters.segment_time_filters[seg_idx]
                    if not self._segment_matches_time_filter(segment, seg_filter):
                        return False
        
        return True
    
    def _segment_matches_time_filter(self, segment: Segment, time_filter: SegmentTimeFilter) -> bool:
        """Check if a segment matches time filter criteria"""
        
        for flight in segment.flight:
            # Check departure time
            if time_filter.departure_time_range:
                if not self._time_in_range(flight.departure_time, time_filter.departure_time_range):
                    return False
            
            # Check arrival time
            if time_filter.arrival_time_range:
                if not self._time_in_range(flight.arrival_time, time_filter.arrival_time_range):
                    return False
        
        return True
    
    def _time_in_range(self, flight_time: str, time_range: TimeRange) -> bool:
        """Check if flight time is within the specified range"""
        if not time_range.start_time and not time_range.end_time:
            return True
        
        try:
            # Parse flight time (assuming format like "14:30")
            flight_time_obj = datetime.strptime(flight_time, '%H:%M').time()
            
            if time_range.start_time:
                start_time_obj = datetime.strptime(time_range.start_time, '%H:%M').time()
                if flight_time_obj < start_time_obj:
                    return False
            
            if time_range.end_time:
                end_time_obj = datetime.strptime(time_range.end_time, '%H:%M').time()
                if flight_time_obj > end_time_obj:
                    return False
            
            return True
        except ValueError:
            # If time parsing fails, assume it matches (don't filter out due to data issues)
            return True
    
    def _sort_proposals(self, proposals: List[Proposal], sorting: SortingMethod) -> List[Proposal]:
        """Sort proposals based on the specified sorting method"""
        
        if sorting == SortingMethod.CHEAP_FIRST:
            return sorted(proposals, key=lambda p: p.get_cheapest_unified_price())
        
        elif sorting == SortingMethod.EARLY_DEPARTURE_FIRST:
            return sorted(proposals, key=lambda p: p.get_earliest_departure_time())
        
        elif sorting == SortingMethod.EARLY_ARRIVAL_FIRST:
            return sorted(proposals, key=lambda p: p.get_latest_arrival_time())
        
        elif sorting == SortingMethod.MINIMAL_DURATION_FIRST:
            return sorted(proposals, key=lambda p: p.total_duration)
        
        else:
            return proposals
        

    
    def get_description(self) -> str:
        """
        Generate a human-readable description of the flight search batch.
        
        Returns:
            A formatted string describing the search results
        """
        if not self.proposals:
            return f"Search results (search_id = {self.search_id}) contains no options."
        
        description_parts = []
        
        # Header with proposal count and segments
        segment_count = len(self.segments)

        description_parts.append(f"Search results (search_id = {self.search_id}) contains {len(self.proposals)} flight options with {segment_count} flight segment{'s' if segment_count != 1 else ''}:")
        
        # Analyze each segment
        for i, segment in enumerate(self.segments, 1):
            origin_airport = self.airports.get(segment.origin, None)
            dest_airport = self.airports.get(segment.destination, None)
            
            origin_name = f"{origin_airport.city} ({segment.origin})" if origin_airport else segment.origin
            dest_name = f"{dest_airport.city} ({segment.destination})" if dest_airport else segment.destination
            
            # Parse date to make it more readable
            try:
                from datetime import datetime
                date_obj = datetime.strptime(segment.date, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d.%m.%Y")
            except:
                formatted_date = segment.date
            
            description_parts.append(f"{i}. from {origin_name} to {dest_name} on departure date {formatted_date}")
        
        # Stops count and pricing analysis
        stops_analysis = self._analyze_stops_and_pricing()
        if stops_analysis:
            description_parts.append(f"Stops count ranges:")
            for stops, min_price in stops_analysis.items():
                stops_text = "direct flights" if stops == 0 else f"{stops} stop{'s' if stops != 1 else ''}"
                description_parts.append(f"- {stops_text} - min price {convert_unified_price_to_user(min_price, self.currency)} {self.currency.upper()}")
        
        # Price range
        unified_prices = []
        for proposal in self.proposals:
            unified_price = proposal.get_cheapest_unified_price()
            unified_prices.append(unified_price)
        
        if unified_prices:
            min_price = min(unified_prices)
            max_price = max(unified_prices)
            description_parts.append(f"Total price ranges from {convert_unified_price_to_user(min_price, self.currency)} {self.currency.upper()} to {convert_unified_price_to_user(max_price, self.currency)} {self.currency.upper()}")
        
        # Duration range
        durations = [p.total_duration for p in self.proposals]
        if durations:
            min_duration = min(durations)
            max_duration = max(durations)
            
            description_parts.append(f"Total duration ranges from {format_duration(min_duration)} to {format_duration(max_duration)}")
        
        # Airlines
        all_carriers = set()
        for proposal in self.proposals:
            all_carriers.update(proposal.carriers)
        
        if all_carriers:
            airline_names = []
            for carrier in sorted(all_carriers):
                airline = self.airlines.get(carrier)
                if airline:
                    airline_names.append(f"{airline.name} ({carrier})")
                else:
                    airline_names.append(carrier)
            
            description_parts.append(f"Airlines options: {', '.join(airline_names)}")
        
        return "\n".join(description_parts)
        
    def _analyze_stops_and_pricing(self) -> Dict[int, int]:
        """Analyze pricing by number of stops."""
        stops_pricing = {}
        
        for proposal in self.proposals:
            stops = proposal.max_stops
            price = proposal.get_cheapest_unified_price()
            
            if stops not in stops_pricing or price < stops_pricing[stops]:
                stops_pricing[stops] = price
        
        return dict(sorted(stops_pricing.items()))

def parse_proposals_batch(api_response: dict) -> ProposalsBatchModel:
    """
    Parse API response dictionary into ProposalsBatchModel.
    
    Args:
        api_response: Dictionary containing the API response
        
    Returns:
        ProposalsBatchModel instance with flattened flight data
    """
    batch = ProposalsBatchModel(**api_response)
    for i in range(len(batch.proposals)):
        batch.proposals[i].batch_ref = batch
    return batch


# Example usage:
"""
# Parse batch
batch = parse_proposals_batch(api_response)

# Create filters
filters = FiltersModel(
    max_total_duration=600,  # 10 hours max
    min_price=100,
    max_price=1000,
    allowed_airlines=["LH", "BA", "AF"],  # Lufthansa, British Airways, Air France
    segment_time_filters=[
        SegmentTimeFilter(
            departure_time_range=TimeRange(start_time="06:00", end_time="22:00"),
            arrival_time_range=TimeRange(start_time="08:00", end_time="23:59")
        )
    ],
    max_stops=1,
    sorting=SortingMethod.CHEAP_FIRST
)

# Apply filters
filtered_batch = batch.apply_filters(filters)

print(f"Original proposals: {len(batch.proposals)}")
print(f"Filtered proposals: {len(filtered_batch.proposals)}")
"""