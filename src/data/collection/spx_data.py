import json
import signal
import sys
import time
from datetime import datetime
from typing import List

import requests

# Define the endpoint URL
endpoint_url = "https://diuz5vjitul6w.cloudfront.net/SPX-Last"

today_date = datetime.now().strftime("%Y-%m-%d")

# Define the path to the output file
output_file = f"/Users/kamyarghiam/Desktop/kalshi_bot/src/data/local/spx/{today_date}"

# Buffer to accumulate results before writing to file
result_buffer: List[str] = []


def hit_endpoint_and_append_result(endpoint_url, result_buffer, max_buffer_size=500):
    try:
        # Make a GET request to the endpoint
        response = requests.get(endpoint_url)

        # Extract the content from the response
        result = json.loads(response.text)
        result = f"{time.time()},{result['price']}"

        # Append the result to the buffer
        result_buffer.append(result)

        # Check if buffer size exceeds the maximum allowed size
        if len(result_buffer) >= max_buffer_size:
            flush_buffer_to_file(result_buffer)

    except requests.RequestException as e:
        print(f"Error occurred: {e}")


def flush_buffer_to_file(result_buffer):
    try:
        # Append all results in the buffer to the output file
        with open(output_file, "a") as file:
            file.write("\n".join(result_buffer) + "\n")

        print(f"Appended {len(result_buffer)} results to {output_file}")

        # Clear the buffer after flushing
        result_buffer.clear()

    except Exception as e:
        print(f"Error occurred while flushing buffer to file: {e}")


def signal_handler(sig, frame):
    # Handle keyboard interrupt (Ctrl+C)
    print("\nKeyboard interrupt detected. Flushing buffer to file...")
    flush_buffer_to_file(result_buffer)
    sys.exit(0)


if __name__ == "__main__":
    # Set up signal handler for keyboard interrupt (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)

    # Run continuously
    try:
        while True:
            hit_endpoint_and_append_result(endpoint_url, result_buffer)
            time.sleep(3)  # Wait for 0.5 seconds before the next request

    except KeyboardInterrupt:
        # Handle keyboard interrupt (Ctrl+C) during the main loop
        print("\nKeyboard interrupt detected. Exiting...")
        flush_buffer_to_file(result_buffer)
        sys.exit(0)
