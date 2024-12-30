import minqlx
import requests
import json
import re

@minqlx.thread
def fetch(self, endpoint, callback, *args, **kwargs):
    self.logger.info(f"Fetching {endpoint}")

    try:
        response = requests.get(endpoint)
        if response.status_code != requests.codes.ok:
            self.logger.error(f"Failed to fetch {endpoint}: {response.status_code}")
            return callback(None, *args, **kwargs)

        data = response.json()
        callback(data, *args, **kwargs)
    except Exception as e:
        self.logger.exception(f"Error fetching {endpoint}: {e}")
        callback(None, *args, **kwargs)

def store_in_redis(self, key, data):
    try:
        serialized_data = json.dumps(data)
        self.db.set(key, serialized_data)
    except Exception as e:
        self.logger.exception(f"Error storing data in Redis: {e}")

def get_from_redis(self, key):
    try:
        return self.db.get(key)
    except Exception as e:
        self.logger.exception(f"Error retrieving data from Redis: {e}")
        return None

def get_json_from_redis(self, key):
    try:
        data = self.db.get(key)
        if data:
            # Need to double load because the data is stored as a string
            return json.loads(data)
    except Exception as e:
        self.logger.exception(f"Error loading data from Redis: {e}")
    return None

def table(headers, rows, title=None):
    """
    Given a list of headers and a list of rows, return a formatted table with a title, separators for each row, and a closing separator line.
    """
    if not headers or not rows:
        return "No data to display."

    MIN_COLUMN_WIDTH = 3

    def strip_formatting(text):
        return re.sub(r"\^\d", "", str(text))

    # Calculate column widths
    max_lengths = [max(len(strip_formatting(header)), MIN_COLUMN_WIDTH) for header in headers]
    for row in rows:
        for i, cell in enumerate(row):
            max_lengths[i] = max(max_lengths[i], len(strip_formatting(cell)))

    # Format headers (align left)
    header_line = "| " + " | ".join(header.ljust(max_lengths[i]) for i, header in enumerate(headers)) + " |"
    separator_line = "+-" + "-+-".join("-" * length for length in max_lengths) + "-+"

    # Format each row (align left for cells)
    row_lines = []
    for row in rows:
        formatted_row = "| " + " | ".join(
            f"{cell}{' ' * (max_lengths[i] - len(strip_formatting(cell)))}"
            for i, cell in enumerate(row)
        ) + " |"
        row_lines.append(formatted_row)

    # Handle the title
    if title:
        total_table_width = len(separator_line)  # Length of the separator line includes borders
        centered_title = f"{title}".center(total_table_width - 2)  # Adjust for side borders
        title_line = f"+{'-' * (total_table_width - 2)}+\n|{centered_title}|\n{separator_line}\n"
    else:
        title_line = ""

    # Combine everything into the final table
    return title_line + "\n".join([header_line, separator_line] + row_lines + [separator_line])
