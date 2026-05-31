import os
import subprocess
import sys

def main():
    print("Building LogDigitizer Engine...")
    
    # Ensure dependencies are installed (optional but good practice)
    # PyInstaller relies on the spec file for execution
    spec_path = os.path.join(os.path.dirname(__file__), "app.spec")
    
    if not os.path.exists(spec_path):
        print(f"Error: Spec file not found at {spec_path}")
        sys.exit(1)
        
    try:
        # Run PyInstaller
        subprocess.run(["pyinstaller", "--noconfirm", spec_path], check=True)
        print("Build completed successfully. Check the 'dist' directory.")
    except subprocess.CalledProcessError as e:
        print(f"Error during build: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
