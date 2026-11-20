import json
import socketio
import os
from typing import Dict, List, Tuple, Union
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from moodscape.backend.emotion_engine import MoodscapeEngine

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "default_secret_key")

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Socket.io with Eventlet for concurrency
sio = socketio.setup(
    ping_timeout=10
)

# Register the app with the socket server
app.wsgi_app = sio.run_app()

class ConnectionManager:
    \"\"\"
    Handles real-time presence and position of users in the 'Parallel Spaces'.
    \"\"\"
    
    def __init__(self):
        # Format: {room_id: {user_id: {x, y, z, status}}}
        self.rooms: Dict[str, Dict[str, Any]] = {}

    def join_room(self, room_id: str, user_id: str):
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        self.rooms[room_id][user_id] = {"status": "connected"}
        print(f"User {user_id} joined room {room_id}")

    def update_position(self, room_id: str, user_id: str, position: dict):
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            self.rooms[room_id][user_id].update(position)
            # Notify others in the room about the position update
            if room_id in self.rooms:
                sio.send(
                    json.dumps({"type": "position_update", "user_id": user_id, "data": position}),
                    room=room_id,
                    include=True,
                    except_silent=True
                )

    def leave_room(self, room_id: str, user_id: str):
        if room_id in self.rooms and user_id in self.rooms[room_id]:
            del self.rooms[room_id][user_id]
            if not self.rooms[room_id]:
                del self.rooms[room_id]

# Global instance
connection_manager = ConnectionManager()
# Initialize the engine
engine = MoodscapeEngine()

@app.route('/')
def index():
    return "Moodscape Parallel Spaces Backend is Running"

@sio.on('connect')
def handle_connect(sid, request_info):
    print(f"Client connected: {sid}")

@sio.on('join')
def on_join(sid, data):
    room_id = data.get("room_id")
    user_id = data.get("user_id")
    if room_id and user_id:
        connection_manager.join_room(room_id, user_id)
        sio.enter_room(sid, room_id)
        print(f"Joined: {user_id} in {room_id}")

@sio.on('update_position')
def on_position_update(sid, data):
    # Expected format: {'room_id': str, 'user_id': str, 'position': {'x': float, 'y': float, 'z': float}}
    room_id = data.get("room_id")
    user_id = data.get("user_id")
    position = data.get("position")
    
    if room_id and user_id and position:
        connection_manager.update_position(room_id, user_id, position)

@sio.on('action')
def on_action(sid, data):
    \"\"\"
    Handles non-verbal, low-pressure interactions (e.g., 'Light', 'Plant').
    This is the core of the 'Silent Connection' model.
    \"\"\"
    room_id = data.get("room_id")
    user_id = data.get("user_id")
    action_type = data.get("action_type") # e.g., 'LIGHT', 'PLANT'
    action_data = data.get("action_data")
    
    if room_id and user_id and action_type:
        # Process the action
        if action_type == "PLANT":
            # Simple mock logic for now
            pass
        elif action_type == "LIGHT":
            # Simple mock logic for now
            pass
            
        # Broadcast the action to everyone else in the room
        # This allows for "Silent" interaction - no chats, just shared reactions.
        sio.send(
            json.dumps({
                "type": "action_event",
                "user_id": user_id,
                "action_type": action_type,
                "action_data": action_data
            }),
            room=room_id,
            include=True,
            except_silent=True
        )

@sio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")
