# M-S2C Diagnostic Engine

M-S2C is a cloud-integrated diagnostic reporting tool built to capture, analyze, and manage software bugs. It combines a TypeScript frontend with comprehensive Google Cloud Platform (GCP) database management to handle file attachments, screenshots, and issue tracking.

## Architecture Overview

| Layer | Responsibility | Key Tech |
| --- | --- | --- |
| Frontend | Bug report UI, file/screenshot upload, repository selection | TypeScript, React, Tailwind CSS |
| Compute/API | Request handling, file processing, issue routing | Node.js, Express |
| Storage | Screenshot and file attachments | Google Cloud Storage (GCP) |
| Database | Bug records, user data, diagnostic logs | Google Cloud Firestore (GCP) |

## Repository Layout

```text
M-S2C-Diagnostic-Engine/
├── frontend/                   # Client-side React application
│   ├── src/
│   │   ├── components/         # UI components (UploadForm, RepoSelect, etc.)
│   │   ├── services/           # API and GCP integration logic
│   │   ├── styles/             # Tailwind CSS configurations
│   │   └── App.tsx             # Main application view
│   ├── package.json
│   └── tsconfig.json
├── backend/                    # Node.js/Express server
│   ├── controllers/            # Request handlers for bug submission
│   ├── routes/                 # API endpoint definitions
│   ├── services/               # GCP Firestore and Storage integration
│   ├── server.ts               # Server entry point
│   └── package.json
├── docs/                       # Project documentation and API contracts
└── README.md
Prerequisites
Google Cloud Platform (GCP) account with Firestore and Cloud Storage enabled.

GCP Service Account JSON key with read/write access to Firestore and Storage.

Node.js 18+ and npm installed.

Local Setup
1. GCP Configuration
Create a Cloud Storage bucket for attachments.

Initialize a Firestore database.

Download your Service Account JSON key and place it in the backend/ directory (ensure this file is gitignored).

2. Backend Initialization
Bash
cd backend
npm install
Create a .env file in the backend/ directory:

Code snippet
PORT=8080
GCP_PROJECT_ID=your-project-id
GCP_KEYFILE_PATH=./your-service-account-key.json
GCS_BUCKET_NAME=your-storage-bucket-name
Start the backend server:

Bash
npm run dev
3. Frontend Initialization
Bash
cd frontend
npm install
Create a .env file in the frontend/ directory:

Code snippet
NEXT_PUBLIC_API_URL=http://localhost:8080/api
Start the frontend development server:

Bash
npm start
The application will be available at http://localhost:3000.

Deployment
Backend (GCP Cloud Run / App Engine)
Ensure your environment variables are configured in your GCP console. Build the TypeScript code and deploy using the gcloud CLI or your preferred CI/CD pipeline.

Frontend (Vercel / Firebase Hosting)
Deploy the frontend/ directory, ensuring the NEXT_PUBLIC_API_URL environment variable points to your deployed backend URL.

Project Status & Next Steps
✅ Developed TypeScript-based diagnostic interface with integrated file and screenshot uploads.

✅ Engineered backend infrastructure utilizing GCP Firestore for structured bug data.

✅ Implemented Google Cloud Storage for handling large diagnostic attachments.

🔜 Integrate automated bug analysis using AI models to suggest immediate fixes based on uploaded logs.
