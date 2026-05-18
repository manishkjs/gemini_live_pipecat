import json
from pathlib import Path

def search_projects(query: str) -> str:
    """Searches projects in Noida/Greater Noida by query string."""
    try:
        json_path = Path(__file__).parent / "projects.json"
        with open(json_path, "r", encoding="utf-8") as f:
            projects = json.load(f)
        
        q = query.lower().strip()
        matches = []
        for p in projects:
            # Safe checks using .get() with default empty strings
            name = p.get("name", "")
            location = p.get("location", "")
            config = p.get("config", "")
            usp = p.get("usp", "")
            
            if (q in name.lower() or 
                q in location.lower() or 
                q in config.lower() or 
                q in usp.lower()):
                
                match_str = (
                    f"- Project: {name}\n"
                    f"  Location: {location}\n"
                    f"  Status: {p.get('status', 'N/A')}\n"
                    f"  Config: {config}\n"
                    f"  Price: {p.get('price', 'Included in Config')}\n"
                    f"  Area: {p.get('area', 'N/A')}\n"
                    f"  USP: {usp}"
                )
                matches.append(match_str)
        
        if not matches:
            return "No projects found matching your preferences."
            
        return "Here are the matching projects I found:\n\n" + "\n\n".join(matches)
    except Exception as e:
        return f"Error performing project search: {str(e)}"
