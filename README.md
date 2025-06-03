# ✈️ Flights MCP Server 

A Model Context Protocol (MCP) server that provides flight search capabilities using the Aviasales Flight Search API. This server allows you to search for flights, filter results, get detailed flight information, and generate booking links.

https://github.com/user-attachments/assets/87d79d54-c4ab-4938-9792-18572315f1ba

## How to use

You can either use the **remote MCP server** or deploy your own instance:

- **Remote MCP**  
  A public instance is available at:  
  `https://findflights.me/sse`  
  This server uses the **SSE** transport protocol and is ready to use without setup.
  > ⚠️ **Important:** Currently not all LLM clients support remote MCP connections. For example, Claude.ai supports remote MCP integrations only on **Pro+ plans**.

- **Self-Hosted Deployment**  
  If you prefer to run your own server, follow the instructions in the [Installation](#installation) section.  
  > **Note**: To deploy your own server, you must obtain an Aviasales API Key and Marker ID.

## Features

- **Flight Search**: Search for one-way, round-trip, and multi-city flights
- **Advanced Filtering**: Filter results by price, duration, airlines, departure/arrival times, and number of stops
- **Multiple Sorting Options**: Sort by price, departure time, arrival time, or duration
- **Detailed Flight Information**: Get comprehensive flight details including baggage allowances and airline information
- **Booking Links**: Generate booking links for selected flights
- **Local Storage**: Performed searches are stored locally so LLM can access past searches without waiting
- **Multiple MCP Transport Options**: Supports stdio, HTTP, and SSE transports

## Installation

### Prerequisites

- Aviasales API key
- Python 3.12 or higher
- UV package manager

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd flights-mcp
```

3. Set up environment variables (see [Environment Variables](#environment-variables) section)

4. Run the server
```bash
uv run src/flights-mcp/main.py
```

## Environment Variables

The following environment variables are required:

- **`FLIGHTS_AVIASALES_API_TOKEN`** *(required)*: Your Aviasales API token

- **`FLIGHTS_AVIASALES_MARKER`** *(required)*: Your Aviasales marker ID

- **`FLIGHTS_TRANSPORT`** *(optional)*: Transport protocol to use
  - Options: `stdio` (default), `streamable_http`, `sse`

- **`FLIGHTS_HTTP_PORT`** *(optional)*: Port for HTTP/SSE transport
  - Only used when `FLIGHTS_TRANSPORT` is `streamable_http` or `sse`
  - Default: `4200`

## MCP Tools

The server provides the following MCP tools:

| Tool                | Description                                                                                                        |
|-------------------------|--------------------------------------------------------------------------------------------------------------------|
| `search_flights`        | Searches for flights using the Aviasales Flight Search API. Returns search description with `search_id` and summary of found options. |
| `get_flight_options`    | Retrieves, filters, and sorts flight options from a previous search. Returns a paginated list of filtered flight options. |
| `get_flight_option_details` | Returns detailed flight information including segments, pricing, baggage allowances, and agency terms.              |
| `request_booking_link`  | Generates a booking link for a specific flight option.                                                              |


## Typical Usage Pattern

1. **Search for flights** using `search_flights()` - Call multiple times for flexible dates
2. **Filter and browse options** using `get_flight_options()` - Lightweight tool, call multiple times with different filters and sorting option
3. **Get detailed information** using `get_flight_option_details()` - For user's preferred options
4. **Generate booking link** using `request_booking_link()` - Only when user confirms booking intent

## Support

For issues related to:
- **MCP Server**: Open an issue in this repository
- **MCP Protocol**: See [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
