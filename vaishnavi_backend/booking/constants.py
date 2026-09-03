from django.db import models
import razorpay
from django.conf import settings

class BookingType(models.TextChoices):
        IN_HOUSE = 'IN_HOUSE', 'In House'
        OPD = 'OPD', 'OPD'
        CLIENT_SIDE = 'CLIENT_SIDE', 'Client Side'
    
class PeriodChoices(models.TextChoices):
    HOURLY = "HOURLY", "Hourly"
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"

class BookingEntity(models.TextChoices):
    VENUE = "VENUE", "Venue"
    SERVICE = "SERVICE", "Service"
    RESOURCE = "RESOURCE", "Resource"

class BookingStatus(models.TextChoices):
    LOBBY = 'LOBBY', 'Lobby'
    HOLD = 'HOLD', 'Hold'
    BOOKED = 'BOOKED', 'Booked'
    DELAYED = 'DELAYED', 'Delayed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    FULFILLED = 'FULFILLED', 'Fulfilled'
    UNFULFILLED = 'UNFULFILLED', 'Unfulfilled'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    YET_TO_START = 'YET_TO_START', 'Yet To Start'
    PARTIALLY_FULFILLED = 'PARTIALLY_FULFILLED', 'Partially Fulfilled'
    MODIFIED = 'MODIFIED', 'Modified'
    RESCHEDULED = 'RESCHEDULED', 'Rescheduled'

MANUAL_STATUS_TRANSITIONS = {
    BookingStatus.LOBBY: [
        BookingStatus.BOOKED,
        BookingStatus.CANCELLED,
    ],
    BookingStatus.BOOKED: [
        BookingStatus.CANCELLED,
        BookingStatus.HOLD,
        BookingStatus.DELAYED,
    ],
    BookingStatus.YET_TO_START: [
        BookingStatus.CANCELLED,
        BookingStatus.HOLD,
        BookingStatus.MODIFIED,
        BookingStatus.RESCHEDULED,
    ],
    BookingStatus.IN_PROGRESS: [
        BookingStatus.CANCELLED,
        BookingStatus.UNFULFILLED,
        BookingStatus.PARTIALLY_FULFILLED,
        BookingStatus.MODIFIED,
        BookingStatus.RESCHEDULED,
    ],
    BookingStatus.HOLD: [
        BookingStatus.BOOKED,
        BookingStatus.IN_PROGRESS,
        BookingStatus.CANCELLED,
    ],
    BookingStatus.UNFULFILLED: [
        BookingStatus.FULFILLED,
        BookingStatus.PARTIALLY_FULFILLED,
    ],
    BookingStatus.PARTIALLY_FULFILLED: [
        BookingStatus.UNFULFILLED,
        BookingStatus.IN_PROGRESS,
    ]
}

class InvoiceStatus(models.TextChoices):
    UNPAID = 'UNPAID', 'Unpaid'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    PAID = 'PAID', 'Paid'
    OVERDUE = 'OVERDUE', 'Overdue'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REFUNDED = 'REFUNDED', 'Refunded'

class PaymentMethod(models.TextChoices):
    CASH = 'CASH', 'Cash'
    UPI = 'UPI', 'UPI'
    CARD = 'CARD', 'Card'
    BANK = 'BANK', 'Bank'
    CHEQUE = 'CHEQUE', 'Cheque'
    RAZORPAY  = 'RAZORPAY', 'Razorpay' 
    WALLET = 'WALLET', 'Wallet'
    WALLET_REFUND = 'WALLET_REFUND', 'Wallet Refund'

RAZORPAY_CLIENT = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
