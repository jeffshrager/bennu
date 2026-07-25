import sys
import re
from typing import TextIO, List, Dict, Union

def parse_log_content(f: TextIO) -> List[Dict[str, Union[str, float]]]:
    """
    Parses log content line-by-line, extracting required sensor data.
    The output fields are 'time', 'methane', 'windspeed', and 'current'.
    Missing or non-numeric values (except time) are replaced with the string 'NA'.
    """
    # Define the required fields
    required_fields = ['time', 'methane', 'windspeed', 'current']
    
    # Robust Regex for the sensor data line: 
    # Searches for "[INFO] Sensors: " followed by the data payload (.*) until the end of the line.
    line_pattern = re.compile(r'\[INFO\]\s+Sensors:\s+(.*)')
    
    # Regex to extract key=value pairs from the payload.
    field_pattern = re.compile(r"(?:(?P<field>[a-z]+)=(?P<value>[^ ]+))")
    
    parsed_data = []

    for raw_line in f:
        # 1. Find the sensor data payload
        line_match = line_pattern.search(raw_line)
        
        if line_match:
            data_string = line_match.group(1).strip()
            
            # 2. Initialize record with 'NA' for safety
            record = {key: 'NA' for key in required_fields}
            
            # 3. Extract key-value pairs
            for field_match in field_pattern.finditer(data_string):
                field_key = field_match.group('field').lower()
                field_value = field_match.group('value')

                if field_key in required_fields:
                    if field_key == 'time':
                        # Time is always kept as a string
                        record[field_key] = field_value
                    else:
                        # Try to convert numeric fields, otherwise keep 'NA'
                        try:
                            record[field_key] = float(field_value)
                        except ValueError:
                            record[field_key] = 'NA'

            # 4. Only keep lines that have a valid 'time' entry
            if record['time'] != 'NA':
                parsed_data.append(record)
                
    return parsed_data

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <log_file_name>", file=sys.stderr)
        sys.exit(1)

    input_filename = sys.argv[1]
    
    try:
        with open(input_filename, 'r') as f:
            data = parse_log_content(f)
    except FileNotFoundError:
        print(f"Error: File not found: {input_filename}", file=sys.stderr)
        sys.exit(1)
        
    # --- Print Header (for easy R import) ---
    header = ['time', 'methane', 'windspeed', 'current']
    print('\t'.join(header))

    # --- Print Data in TSV format ---
    for record in data:
        # Convert all values to string, including floats and 'NA'
        row = [str(record[f]) for f in header]
        print('\t'.join(row))

if __name__ == "__main__":
    main()
