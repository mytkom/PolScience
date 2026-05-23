import os
import requests
import zipfile


if __name__ == "__main__":
    # Example usage
    url = "https://cernbox.cern.ch/remote.php/dav/public-files/FzVVsFiuFD8P0Yy/LudzieNaukiDumpDB.zip"
    save_path = os.path.join("LudzieNaukiDumpDB.zip")

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Check if the request was successful

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"File downloaded successfully and saved to {save_path}")

        # Unzip the downloaded file
        with zipfile.ZipFile(save_path, 'r') as zip_ref:
            zip_ref.extractall("test_LudzieNaukiDumpDB")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while downloading the file: {e}")
    except zipfile.BadZipFile as e:
        print(f"An error occurred while unzipping the file: {e}")