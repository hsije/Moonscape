import random
from typing import Dict, List, Tuple, Union

class MoodscapeEngine:
    # The core engine that translates emotional input into a multi-dimensional 
    # emotional vector, and subsequently into visuals for the 'Island'.
    
    def __init__(self):
        # Mapping Vector Profiles to Visual Elements
        # Dimensions:
        #   - Energy (0.0 - 1.0): Activity, weather, and particle intensity.
        #   - Valence (0.0 - 1.0): Positive vs Negative (Warmth vs Cold).
        #   - Tension (0.0 - 1.0): Sharpness and structural complexity.
        #   - Clarity (0.0 - 1.0): Minimalist vs Dense/Complex environment.
        
        self.visual_profiles = {
            "anxious": {
                "energy": 0.8, "valence": 0.2, "tension": 0.9, "clarity": 0.4,
                "palette": ["#4A5568", "#2D3748", "#718096"],
                "elements": ["sharp crystals", "floating fragments", "electric sparks"],
                "weather": "fast-moving storm clouds",
                "terrain": "jagged peaks"
            },
            "calm": {
                "energy": 0.2, "valence": 0.8, "tension": 0.2, "clarity": 0.7,
                "palette": ["#B2F5EA", "#81E6D9", "#C6F6D5"],
                "elements": ["glowing jellyfish", "slow ripples", "floating petals"],
                "weather": "soft golden hour haze",
                "terrain": "rolling hills"
            },
            "lonely": {
                "energy": 0.1, "valence": 0.4, "tension": 0.3, "clarity": 0.9,
                "palette": ["#1A202C", "#2D3748", "#4A5568"],
                "elements": ["single warm lantern", "distant stars", "still water"],
                "weather": "clear starry night",
                "terrain": "small solitary mound"
            },
            "happy": {
                "energy": 0.9, "valence": 0.9, "tension": 0.4, "clarity": 0.6,
                "palette": ["#FBD38D", "#F6AD55", "#FEEBC8"],
                "elements": ["dancing sparks", "blooming neon flowers", "floating bubbles"],
                "weather": "bright sunlight with rainbows",
                "terrain": "vibrant plateau"
            },
            "sad": {
                "energy": 0.2, "valence": 0.2, "tension": 0.6, "clarity": 0.5,
                "palette": ["#A0AEC0", "#718096", "#4A5568"],
                "elements": ["falling rain drops", "wilting lilies", "deep puddles"],
                "weather": "continuous light drizzle",
                "terrain": "sunken basin"
            }
        }

    def analyze_emotion(self, text: str) -> Dict[str, any]:
        # Analyzes text for multi-dimensional emotion vectors.
        text = text.lower()
        
        detected_emotion = "neutral"
        for emotion in self.visual_profiles.keys():
            if emotion in text:
                detected_emotion = emotion
                break
        
        return self.visual_profiles.get(detected_emotion, {
            "energy": 0.5, "valence": 0.5, "tension": 0.5, "clarity": 0.5,
            "palette": ["#E2E8F0", "#CBD5E0", "#A0AEC0"],
            "elements": ["floating spheres", "mist"],
            "weather": "neutral fog",
            "terrain": "flat plain"
        })

    def generate_visual_prompt(self, text: str) -> Dict[str, any]:
        # Generates AI prompts based on emotional vectors.
        mood = self.analyze_emotion(text)
        
        prompt = (
            f"A surreal 3D floating island in a void. "
            f"Terrain: {mood['terrain']} (Intensity: {mood['tension']*100:.0f}%). "
            f"Atmosphere: {mood['weather']}. "
            f"Key elements: {', '.join(mood['elements'])}. "
            f"Color palette: {', '.join(mood['palette'])}. "
            f"Style: { 'High-complexity' if mood['clarity'] < 0.5 else 'Minimalist' } art. "
            f"Hyper-realistic, cinematic lighting, 8k, octane render, whimsical, emotional atmosphere."
        )
        
        return {
            "visual_params": mood,
            "ai_prompt": prompt
        }

    def calculate_evolution(self, current_stats: Dict[str, any], latest_emotion: str) -> Dict[str, any]:
        # Calculates growth based on recurring emotion frequency.
        freq_map = current_stats.get("frequency_map", {})
        freq_map[latest_emotion] = freq_map.get(latest_emotion, 0) + 1
        
        new_status = "stable"
        if freq_map.get("calm", 0) > 3 and current_stats.get("growth_status") != "forest":
            new_status = "forest_growth"
        elif freq_map.get("happy", 0) > 5 and current_stats.get("growth_status") != "habitat":
            new_status = "habitat_expansion"
            
        return {
            "frequency_map": freq_map,
            "growth_status": new_status
        }

if __name__ == "__main__":
    engine = MoodscapeEngine()
    # Mock initial state
    current_stats = {
        "frequency_map": {"calm": 2},
        "growth_status": "stable"
    }
    
    # Test simulation
    test_input = "I feel so calm and peaceful today."
    
    # 1. Analysis
    mood_params = engine.analyze_emotion(test_input)
    print(f"Input: {test_input}")
    print(f"Detected: {list(engine.visual_profiles.keys())}")
    
    # 2. Evolution Check
    new_stats = engine.calculate_evolution(current_stats, "calm")
    print(f"Current Status: {current_stats['growth_status']}")
    print(f"New Growth Status: {new_stats['growth_status']}")
    print(f"Update: {new_stats['frequency_map']}")
    
    # 3. Prompt Generation
    print(f"Prompt: {engine.generate_visual_prompt(test_input)['ai_prompt']}")
    print("-" * 30)
