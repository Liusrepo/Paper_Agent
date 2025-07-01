"""System Setup Test

Validates API connectivity and system configuration.
"""

import asyncio
import os
from pathlib import Path

from config import load_config
from utils import setup_logger, validate_material_id


async def test_api_connectivity():
    """Test connectivity to all APIs."""
    print("🔧 Testing API Connectivity...")
    
    try:
        api_config, app_config = load_config()
        logger = setup_logger()
        
        print(f"✅ Configuration loaded successfully")
        
        # Test Materials Project
        print("\n🧪 Testing Materials Project API...")
        try:
            from materials_client import MaterialsProjectClient
            from utils import RateLimiter
            
            mp_client = MaterialsProjectClient(api_config, RateLimiter(60))
            is_valid = await mp_client.validate_material_id("mp-1")
            
            if is_valid:
                print("✅ Materials Project API: Connected")
            else:
                print("⚠️ Materials Project API: Connection issue")
                
        except Exception as e:
            print(f"❌ Materials Project API: {e}")
        
        # Test Semantic Scholar
        print("\n📚 Testing Semantic Scholar API...")
        try:
            from search_client import SemanticScholarClient
            
            search_client = SemanticScholarClient(api_config, RateLimiter(90))
            is_valid = await search_client.validate_api_access()
            
            if is_valid:
                print("✅ Semantic Scholar API: Connected")
            else:
                print("⚠️ Semantic Scholar API: Connection issue")
                
        except Exception as e:
            print(f"❌ Semantic Scholar API: {e}")
        
        # Test Gemini
        print("\n🧠 Testing Gemini AI API...")
        try:
            from gemini_client import GeminiClient
            
            gemini_client = GeminiClient(api_config, RateLimiter(15))
            is_valid = await gemini_client.validate_api_access()
            
            if is_valid:
                print("✅ Gemini AI API: Connected")
            else:
                print("⚠️ Gemini AI API: Connection issue")
                
        except Exception as e:
            print(f"❌ Gemini AI API: {e}")
        
        # Test file system
        print("\n📁 Testing File System...")
        try:
            from file_manager import FileManager
            
            file_manager = FileManager()
            workspace = file_manager.create_material_workspace("test")
            
            if workspace.exists():
                print("✅ File system: Working")
                # Clean up test workspace
                import shutil
                shutil.rmtree(workspace)
            else:
                print("❌ File system: Cannot create directories")
                
        except Exception as e:
            print(f"❌ File system: {e}")
        
    except Exception as e:
        print(f"❌ Configuration error: {e}")


def test_dependencies():
    """Test that all required dependencies are installed."""
    print("📦 Testing Dependencies...")
    
    dependencies = [
        ("requests", "HTTP client"),
        ("google.generativeai", "Gemini AI"),
        ("mp_api", "Materials Project"),
        ("bs4", "BeautifulSoup HTML parsing"),
        ("dotenv", "Environment management"),
        ("PyPDF2", "PDF processing"),
    ]
    
    optional_dependencies = [
        ("fitz", "PyMuPDF PDF processing"),
        ("scholarly", "Google Scholar"),
    ]
    
    all_good = True
    
    for module, description in dependencies:
        try:
            __import__(module)
            print(f"✅ {module}: {description}")
        except ImportError:
            print(f"❌ {module}: {description} - MISSING")
            all_good = False
    
    print("\n📦 Optional Dependencies:")
    for module, description in optional_dependencies:
        try:
            __import__(module)
            print(f"✅ {module}: {description}")
        except ImportError:
            print(f"⚠️ {module}: {description} - Optional, not installed")
    
    return all_good


def test_environment():
    """Test environment setup."""
    print("🌍 Testing Environment Setup...")
    
    required_vars = [
        "MP_API_KEY",
        "GEMINI_API_KEY", 
        "ELSEVIER_API_KEY"
    ]
    
    optional_vars = [
        "SEMANTIC_SCHOLAR_API_KEY",
        "ANNA_ARCHIVE_API_KEY"
    ]
    
    all_good = True
    
    print("\n🔑 Required API Keys:")
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: Set ({'*' * 8}{value[-4:] if len(value) > 4 else value})")
        else:
            print(f"❌ {var}: Not set")
            all_good = False
    
    print("\n🔑 Optional API Keys:")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: Set ({'*' * 8}{value[-4:] if len(value) > 4 else value})")
        else:
            print(f"⚠️ {var}: Not set (optional)")
    
    return all_good


def test_input_validation():
    """Test input validation functions."""
    print("\n🔍 Testing Input Validation...")
    
    test_cases = [
        ("mp-20783", True, "Valid Materials Project ID"),
        ("20783", True, "Valid numeric ID (auto-converts)"),
        ("", False, "Empty ID"),
        ("invalid", False, "Invalid format"),
        ("mp-", False, "Incomplete ID"),
    ]
    
    for test_input, expected, description in test_cases:
        try:
            result = validate_material_id(test_input)
            if expected:
                print(f"✅ '{test_input}' → '{result}': {description}")
            else:
                print(f"⚠️ '{test_input}': Should have failed but got '{result}'")
        except ValueError:
            if not expected:
                print(f"✅ '{test_input}': Correctly rejected - {description}")
            else:
                print(f"❌ '{test_input}': Incorrectly rejected - {description}")


async def main():
    """Main test function."""
    print("🧪 Materials Research Paper Analysis System")
    print("📋 System Setup Test")
    print("=" * 60)
    
    # Test 1: Dependencies
    deps_ok = test_dependencies()
    
    # Test 2: Environment
    env_ok = test_environment()
    
    # Test 3: Input validation
    test_input_validation()
    
    # Test 4: API connectivity (only if basic setup is ok)
    if deps_ok and env_ok:
        await test_api_connectivity()
    else:
        print("\n⚠️ Skipping API tests due to missing dependencies or environment")
    
    # Final summary
    print("\n" + "=" * 60)
    if deps_ok and env_ok:
        print("🎉 System appears to be properly configured!")
        print("✅ Ready to run: python main.py")
    else:
        print("⚠️ System configuration incomplete")
        print("📖 Please refer to README.md for setup instructions")
        
        if not deps_ok:
            print("   → Install missing dependencies: pip install -r requirements.txt")
        
        if not env_ok:
            print("   → Set up API keys in .env file")


if __name__ == "__main__":
    asyncio.run(main()) 