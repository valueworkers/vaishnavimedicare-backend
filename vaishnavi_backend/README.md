# Eventroop Backend

A comprehensive event/venue management and healthcare service booking platform built with Django REST Framework.

## Overview

Eventroop is a multi-tenant SaaS platform supporting two primary domains:
- **valueoccasions.com** — Event and venue booking management
- **vaishnavimedicare.com** — Healthcare service booking

It provides end-to-end management including venue listings, complex order workflows, attendance tracking, payroll, multi-channel notifications, invoicing, and a customer wallet system.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend Framework | Django 6.0.3 + Django REST Framework 3.17.1 |
| ASGI Server | Daphne 4.2.1 (WebSocket) |
| WSGI Server | Gunicorn (production) |
| Database | PostgreSQL 15+ via Neon (serverless) |
| Cache / Message Broker | Redis 7.4 |
| Async Tasks | Celery 5.6.2 + Celery Beat 2.9.0 |
| Real-time | Django Channels 4.3.2 |
| Authentication | JWT (djangorestframework-simplejwt) |
| File Storage | Cloudinary |
| SMS / WhatsApp | Twilio |
| Email | Gmail SMTP |
| Push Notifications | Firebase (FCM) / APNS |
| AI Integration | OpenAI |

---

## Features

- **Multi-role User Management** — Master Admin, VSRE Owner, Manager, Staff, Customer with hierarchical relationships
- **Venue Management** — Venue profiles, photos, amenities, services, pricing packages
- **Three-level Order System** — Primary → Secondary → Ternary orders for complex billing
- **Healthcare Booking** — Patient registration, document uploads, medical information tracking
- **Attendance Tracking** — Time-based attendance with status (Present, Absent, Half Day, Leave)
- **Payroll Management** — Salary structures, increments, advances, loans, salary reports
- **Financial Management** — Invoice generation, payment tracking, customer wallet with debit/credit
- **Multi-channel Notifications** — WhatsApp, SMS, Email, In-App, Voice with template management
- **Real-time Updates** — WebSocket support for notifications and attendance
- **Analytics & Reporting** — Salary, attendance, and payment reports
- **FAQ & Help Center** — FAQ topics with Q&A and video tutorials

---

## Project Structure

```
vaishnavi_backend/
├── vaishnavi_backend/      # Django project config (settings, urls, celery, asgi)
├── accounts/               # User auth, registration, OTP, permissions
├── venue_manager/          # Venue and service CRUD
├── booking/                # Order system, patients, invoices, payments
├── attendance/             # Attendance tracking + WebSocket consumer
├── payroll/                # Salary structures and transactions
├── notification/           # Multi-channel notification system + WebSocket
├── analysis/               # Analytics and reporting endpoints
├── wallet/                 # Customer wallet and transactions
├── faq/                    # FAQ topics, items, and video tutorials
├── requirements.txt
├── Procfile                # Heroku/Gunicorn deployment
└── vercel.json             # Vercel deployment config
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7.4+

---

## Setup & Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd vaishnavi_backend

# 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your credentials

# 5. Apply migrations
python manage.py migrate

# 6. Create superuser
python manage.py createsuperuser

# 7. Collect static files
python manage.py collectstatic
```

---

## Running the Application

Open separate terminals for each process:

```bash
# Django development server
python manage.py runserver

# Celery worker (async tasks)
celery -A vaishnavi_backend worker -l info

# Celery Beat (scheduled tasks)
celery -A vaishnavi_backend beat -l info

# Daphne ASGI server (WebSockets)
daphne -b 0.0.0.0 -p 8001 vaishnavi_backend.asgi:application
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Redis
REDIS_URL=redis://127.0.0.1:6379

# JWT
ACCESS_TOKEN_LIFETIME_MINUTES=1440
REFRESH_TOKEN_LIFETIME_DAYS=7

# Cloudinary
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Twilio (SMS / WhatsApp)
TWILIO_ACCOUNT_SID=your-sid
TWILIO_AUTH_TOKEN=your-token
TWILIO_PHONE_NUMBER=+1234567890
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# Email (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com

# Firebase Push Notifications (optional)
FCM_API_KEY=your-firebase-key
```

---

## API Endpoints

### Authentication — `/accounts/`

| Method | Endpoint | Description |
|---|---|---|
| POST | `/accounts/register/customer/` | Register customer |
| POST | `/accounts/register/owner/` | Register venue owner |
| POST | `/accounts/login/` | Login (returns JWT) |
| POST | `/accounts/logout/` | Logout |
| POST | `/accounts/token/refresh/` | Refresh access token |
| POST | `/accounts/request-otp/` | Request OTP for password reset |
| POST | `/accounts/verify-otp/` | Verify OTP |
| POST | `/accounts/password-reset/` | Reset password |

### Venue Management — `/management/`

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/management/venues/` | List / create venues |
| GET/PUT/DELETE | `/management/venues/<id>/` | Venue detail operations |
| GET/POST | `/management/services/` | List / create services |

### Bookings — `/booking/`

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/booking/bookings/` | Create / list orders |
| GET/POST | `/booking/invoices/` | Invoice management |
| GET/POST | `/booking/payments/` | Payment tracking |
| GET | `/booking/public-venues/` | Public venue listing |
| POST | `/booking/patients/` | Register patient |
| POST | `/booking/location/` | Add location |

### Attendance — `/attendance/`

| Method | Endpoint | Description |
|---|---|---|
| POST | `/attendance/attendance/` | Mark attendance |
| GET | `/attendance/total-attendance/` | Attendance report |
| GET | `/attendance/attendance-status/` | Attendance statuses |
| WS | `/ws/attendance/` | Real-time attendance WebSocket |

### Payroll — `/payroll/`

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/payroll/salary-structures/` | Salary structure management |
| GET | `/payroll/salary-report/` | Salary reports |

### Notifications — `/notifications/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/notifications/notifications/` | List notifications |
| POST | `/notifications/templates/` | Create notification template |
| WS | `/ws/notifications/` | Real-time notifications WebSocket |

### Analysis — `/analysis/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analysis/salary/` | Salary analysis |
| GET | `/analysis/attendance/` | Attendance analysis |
| GET | `/analysis/payment-master/` | Payment master report |

### Wallet — `/wallet/`

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/wallet/wallet/` | Wallet operations |

### FAQ — `/faq/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/faq/faq/` | List FAQ topics and items |
| GET | `/faq/video/` | List FAQ videos |

---

## Background Tasks (Celery Beat)

| Schedule | Task | Description |
|---|---|---|
| Every 5 minutes | `booking.tasks.update_statuses_by_time` | Auto-update order statuses |
| 8:00 AM daily | `notifications.tasks.send_daily_digest` | Send daily notification digest |
| 11:30 PM daily | `booking.tasks.trigger_auto_continue_secondary_orders` | Auto-continue recurring orders |
| Midnight daily | `attendance.tasks.mark_attendance_present` | Auto-mark attendance |

---

## Deployment

### Heroku
The project includes a `Procfile` configured for Gunicorn:
```
web: gunicorn vaishnavi_backend.wsgi
```

### Vercel
Configured via `vercel.json` with Python 3.11 runtime.

---

## Running Tests

```bash
# Run all tests
python manage.py test

# Run tests for a specific app
python manage.py test accounts
python manage.py test booking
```

---

## Branches

| Branch | Purpose |
|---|---|
| `main` | Production-ready code |
| `dev` | Active development |
| `mayur-dev` | Feature development |
