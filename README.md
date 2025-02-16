# Hikvision Enviz Camera Integration

This integration provides support for Hikvision Enviz cameras in Home Assistant using the native Hikvision SDK.

## Features

- Native SDK streaming (better performance than RTSP)
- PTZ control support
- Snapshot capabilities
- Direct frame processing

## Installation

### HACS Installation
1. Open HACS
2. Click on "Integrations"
3. Click the three dots in the top right
4. Select "Custom repositories"
5. Add this repository URL
6. Select "Integration" as the category

### Manual Installation
1. Copy the `custom_components/hikvision_enviz` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "Hikvision Enviz"
4. Enter your camera's:
   - IP address
   - Port (usually 8000)
   - Username
   - Password

## Requirements

- Home Assistant 2023.8.0 or newer
- Hikvision SDK libraries (included)

## License

This project is licensed under the MIT License - see the LICENSE file for details. 