#!/usr/bin/env python3
"""
Material Research Paper Analysis System - Usage Example

This example demonstrates how to use this system for material paper analysis.
"""

import sys
import asyncio
from pathlib import Path

# Add src directory to Python path (for development environment)
current_dir = Path(__file__).parent.parent
src_dir = current_dir / "src"
sys.path.insert(0, str(src_dir))

async def example_analysis():
    """Example analysis workflow"""
    
    print("🔬 Material Research Paper Analysis System - Example")
    print("=" * 50)
    
    # Import main components
    from config import load_config
    from core.file_manager import FileManager
    from clients.materials_client import MaterialsProjectClient
    from clients.search_client import SemanticScholarClient
    from clients.gemini_client import GeminiClient
    from utils.utils import RateLimiter
    
    try:
        # Load configuration
        api_config, app_config = load_config()
        
        # Create file manager
        file_manager = FileManager(app_config.base_dir)
        
        # Create rate limiter
        mp_limiter = RateLimiter(app_config.rate_limits['materials_project'])
        
        # Create Materials Project client
        materials_client = MaterialsProjectClient(api_config, mp_limiter)
        
        # Example: Get material information
        material_id = "mp-20738"  # β-FeSi2 example
        print(f"\n📡 Getting material information: {material_id}")
        
        material = await materials_client.get_material_info(material_id)
        if material:
            print(f"✅ Material: {material['formula']}")
            print(f"   Density: {material.get('density', 'N/A')} g/cm³")
            print(f"   Space Group: {material.get('spacegroup', 'N/A')}")
        
        print("\n💡 For complete analysis, please use:")
        print("   python run.py")
        print("   Then input material ID and paper count")
        
    except Exception as e:
        print(f"❌ Example run error: {e}")
        print("📝 Please ensure .env file is configured and all dependencies are installed")

def main():
    """Main function"""
    asyncio.run(example_analysis())

if __name__ == "__main__":
    main() 