from flask import Flask, request
import requests
import xmltodict
import math
import redis
import json
from datetime import datetime, timezone
from geopy.geocoders import Nominatim
import time
from astropy import coordinates, units
from typing import List, Dict, Tuple

# Initialize Flask app
app = Flask(__name__)

# Set up Redis client (using container name in Docker Compose)
rd = redis.Redis(host="redis-db", port=6379, db=0, decode_responses=True)

# Set up GeoPy Nominatim geocoder
geocoder = Nominatim(user_agent='iss_tracker')

# NASA ISS data source URL
ISS_DATA_URL = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml"


def fetch_iss_data(url: str = ISS_DATA_URL) -> str:
    """Fetches ISS trajectory XML data from NASA's public data source."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print("Error fetching ISS data:", e)
        return ""


def parse_iss_data(xml_data: str) -> List[Dict[str, object]]:
    """Parses the XML data into a list of dictionaries."""
    try:
        data = xmltodict.parse(xml_data)
        state_vectors = data["ndm"]["oem"]["body"]["segment"]["data"]["stateVector"]
        iss_data = []
        for vec in state_vectors:
            # Parse epoch (format: 'YYYY-DDDT HH:MM:SS.sssZ')
            epoch_dt = datetime.strptime(vec["EPOCH"], "%Y-%jT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            epoch_iso = epoch_dt.isoformat()
            entry = {
                "epoch": epoch_iso,
                "position": [
                    float(vec["X"]["#text"]),
                    float(vec["Y"]["#text"]),
                    float(vec["Z"]["#text"])
                ],
                "velocity": [
                    float(vec["X_DOT"]["#text"]),
                    float(vec["Y_DOT"]["#text"]),
                    float(vec["Z_DOT"]["#text"])
                ]
            }
            iss_data.append(entry)
            
            rd.hset("iss_data", epoch_iso, json.dumps(entry))

        for entry in iss_data:
            entry["epoch"] = datetime.fromisoformat(entry["epoch"])
        return iss_data
    except (KeyError, ValueError, TypeError) as e:
        print("Error parsing ISS data:", e)
        return []


def get_iss_data() -> List[Dict[str, object]]:
    """Retrieves ISS data from Redis if available; otherwise, fetches and parses it."""
    try:
        if rd.hlen("iss_data") == 0:
            xml_data = fetch_iss_data()
            if not xml_data:
                return []
            return parse_iss_data(xml_data)
        data = []
        for value in rd.hvals("iss_data"):
            entry = json.loads(value)
            entry["epoch"] = datetime.fromisoformat(entry["epoch"])
            data.append(entry)
        return data
    except Exception as e:
        print("Error retrieving ISS data:", e)
        return []


def compute_speed(velocity: Tuple[float, float, float]) -> float:
    """Calculates the instantaneous speed (km/s) from a velocity vector."""
    return math.sqrt(velocity[0] ** 2 + velocity[1] ** 2 + velocity[2] ** 2)


def compute_average_speed(data: List[Dict[str, object]]) -> float:
    """Computes the average instantaneous speed (km/s) across all state vector entries."""
    speeds = [compute_speed(tuple(entry["velocity"])) for entry in data]
    return sum(speeds) / len(speeds) if speeds else 0.0


def find_closest_epoch(data: List[Dict[str, object]], now: datetime) -> Dict[str, object]:
    """Finds the ISS state vector entry with an epoch closest to the current time."""
    return min(data, key=lambda d: abs(d["epoch"] - now))


def compute_location_astropy(entry: Dict[str, object]) -> Tuple[float, float, float]:
    """Converts an ISS state vector entry into geodetic coordinates (latitude, longitude, altitude)
    using Astropy."""
    x, y, z = entry["position"]
    epoch_str = entry["epoch"].strftime('%Y-%jT%H:%M:%S.000Z')
    this_epoch = time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(epoch_str[:-5], '%Y-%jT%H:%M:%S'))
    cartrep = coordinates.CartesianRepresentation([x, y, z], unit=units.km)
    gcrs = coordinates.GCRS(cartrep, obstime=this_epoch)
    itrs = gcrs.transform_to(coordinates.ITRS(obstime=this_epoch))
    loc = coordinates.EarthLocation(*itrs.cartesian.xyz)
    return loc.lat.value, loc.lon.value, loc.height.value


def reverse_geocode(lat: float, lon: float) -> str:
    """Uses GeoPy's Nominatim to reverse geocode latitude and longitude into a human-readable address."""
    try:
        location = geocoder.reverse((lat, lon), zoom=10, language='en')
        return location.address if location else "Geoposition not found"
    except Exception as e:
        print("Error in reverse geocoding:", e)
        return "Geoposition lookup failed"


@app.route("/epochs", methods=["GET"])
def epochs():
    """
      - Without query parameters: Returns the entire data set.
      - With query parameters (limit & offset): Returns a modified list of epochs.
    """
    try:
        data = get_iss_data()
        data.sort(key=lambda d: d["epoch"])
        limit = request.args.get("limit", type=int)
        offset = request.args.get("offset", default=0, type=int)
        subset = data[offset: offset + limit] if limit is not None else data[offset:]
        return "\n".join([entry["epoch"].isoformat(timespec="seconds") for entry in subset]) + "\n"
    except Exception as e:
        return f"Error retrieving epochs: {e}", 500


@app.route("/epochs/<epoch>", methods=["GET"])
def epoch_detail(epoch: str):
    """Returns the state vectors (position and velocity) for a specific epoch."""
    try:
        data = get_iss_data()
        for entry in data:
            if entry["epoch"].isoformat(timespec="seconds") == epoch:
                output = (
                    f"Epoch: {entry['epoch'].isoformat(timespec='seconds')}\n"
                    f"Position: {entry['position']}\n"
                    f"Velocity: {entry['velocity']}\n"
                )
                return output
        return "Epoch not found", 404
    except Exception as e:
        return f"Error retrieving epoch: {e}", 500


@app.route("/epochs/<epoch>/speed", methods=["GET"])
def epoch_speed(epoch: str):
    """Returns the instantaneous speed (km/s) for a specific epoch."""
    try:
        data = get_iss_data()
        for entry in data:
            if entry["epoch"].isoformat(timespec="seconds") == epoch:
                speed = compute_speed(tuple(entry["velocity"]))
                output = (
                    f"Epoch: {epoch}\n"
                    f"Instantaneous Speed: {speed:.2f} km/s\n"
                )
                return output
        return "Epoch not found", 404
    except Exception as e:
        return f"Error computing speed: {e}", 500


@app.route("/epochs/<epoch>/location", methods=["GET"])
def epoch_location(epoch: str):
    """Returns the latitude, longitude, altitude, and geoposition for a specific epoch."""
    try:
        data = get_iss_data()
        for entry in data:
            if entry["epoch"].isoformat(timespec="seconds") == epoch:
                lat, lon, alt = compute_location_astropy(entry)
                geopos = reverse_geocode(lat, lon)
                output = (
                    f"Epoch: {epoch}\n"
                    f"Latitude: {lat}\n"
                    f"Longitude: {lon}\n"
                    f"Altitude: {alt:.2f} km\n"
                    f"Geoposition: {geopos}\n"
                )
                return output
        return "Epoch not found", 404
    except Exception as e:
        return f"Error computing location: {e}", 500


@app.route("/now", methods=["GET"])
def now():
    """
    Returns details for the epoch nearest to the current time, including:
        - Instantaneous speed
        - Position and velocity
        - Latitude, longitude, altitude, and geoposition
    """
    try:
        data = get_iss_data()
        if not data:
            return "No ISS data available", 500
        now_time = datetime.now(timezone.utc)
        closest = find_closest_epoch(data, now_time)
        avg_speed = compute_average_speed(data)
        lat, lon, alt = compute_location_astropy(closest)
        geopos = reverse_geocode(lat, lon)
        output = (
            f"Closest Epoch: {closest['epoch'].isoformat(timespec='seconds')}\n"
            f"Position: {closest['position']}\n"
            f"Velocity: {closest['velocity']}\n"
            f"Instantaneous Speed: {compute_speed(tuple(closest['velocity'])):.2f} km/s\n"
            f"Average ISS Speed: {avg_speed:.2f} km/s\n"
            f"Latitude: {lat}\n"
            f"Longitude: {lon}\n"
            f"Altitude: {alt:.2f} km\n"
            f"Geoposition: {geopos}\n"
        )
        return output
    except Exception as e:
        return f"Error retrieving current ISS data: {e}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
