#!/usr/bin/env python3
"""
Materials Research Paper Analysis System - Launcher

"""

import sys
import os
from pathlib import Path

# Add src directory to Python path
current_dir = Path(__file__).parent
src_dir = current_dir / "src"
sys.path.insert(0, str(src_dir))

def main():
    """Main function"""
    print("🔬 Materials Research Paper Analysis System")
    print("=" * 60)
    
    # Check .env file
    env_file = current_dir / ".env"
    if not env_file.exists():
        print("❌ .env file not found")
        print("📝 Please copy .env.template to .env and configure API keys")
        print(f"   cp {current_dir}/.env.template {current_dir}/.env")
        return
    
    try:
        # Import and run main program
        from main import main as run_main
        import asyncio
        asyncio.run(run_main())
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("📝 Please ensure all dependencies are installed:")
        print("   pip install -r requirements.txt")
    except Exception as e:
        print(f"❌ Runtime error: {e}")

if __name__ == "__main__":
    main() 