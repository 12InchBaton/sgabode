from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    Text, BigInteger, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Buyer(Base):
    __tablename__ = "buyers"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    whatsapp_number = Column(String(20))
    name = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    preferences = relationship(
        "BuyerPreference", back_populates="buyer", cascade="all, delete-orphan"
    )
    matches = relationship("Match", back_populates="buyer")
    viewing_requests = relationship("ViewingRequest", back_populates="buyer")


class BuyerPreference(Base):
    __tablename__ = "buyer_preferences"

    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False)

    intent = Column(String(10))  # buy | rent
    property_types = Column(ARRAY(String), default=list)
    price_min = Column(Float)
    price_max = Column(Float)
    floor_size_min = Column(Float)
    floor_size_max = Column(Float)
    bedrooms = Column(ARRAY(Integer), default=list)
    bathrooms = Column(ARRAY(Integer), default=list)
    districts = Column(ARRAY(Integer), default=list)
    mrt_distance_max = Column(Integer)   # metres
    tenure = Column(ARRAY(String), default=list)
    floor_level_min = Column(Integer)
    floor_level_max = Column(Integer)
    build_year_min = Column(Integer)
    psf_min = Column(Float)
    psf_max = Column(Float)
    unit_features = Column(ARRAY(String), default=list)
    facilities = Column(ARRAY(String), default=list)
    furnishing = Column(ARRAY(String), default=list)
    keywords = Column(Text)

    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    buyer = relationship("Buyer", back_populates="preferences")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True)
    phone = Column(String(20))
    agency = Column(String(255))
    cea_number = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listings = relationship("Listing", back_populates="agent")
    viewing_requests = relationship("ViewingRequest", back_populates="agent")
    payments = relationship("ListingPayment", back_populates="agent")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), default="manual")
    source_url = Column(Text)
    external_id = Column(String(255))
    submitted_by = Column(Integer, ForeignKey("agents.id"), nullable=True)

    title = Column(String(500))
    description = Column(Text)
    property_type = Column(String(50))   # hdb | condo | landed | commercial
    intent = Column(String(10))          # buy | rent

    address = Column(Text)
    postal_code = Column(String(10))
    district = Column(Integer)
    latitude = Column(Float)
    longitude = Column(Float)

    asking_price = Column(Float)
    floor_size = Column(Float)           # sqft
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    floor_level = Column(Integer)
    total_floors = Column(Integer)
    build_year = Column(Integer)
    tenure = Column(String(50))          # freehold | 99-year | 999-year
    psf = Column(Float)
    nearest_mrt = Column(String(255))
    mrt_distance = Column(Integer)       # metres

    unit_features = Column(ARRAY(String), default=list)
    facilities = Column(ARRAY(String), default=list)
    furnishing = Column(String(50))      # unfurnished | partial | fully

    ai_summary = Column(Text)
    ai_layout_notes = Column(Text)
    ai_generated_at = Column(DateTime(timezone=True))

    status = Column(String(20), default="active")
    verified = Column(Boolean, default=False)
    is_paid = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent = relationship("Agent", back_populates="listings")
    media = relationship(
        "ListingMedia",
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="ListingMedia.display_order",
    )
    matches = relationship("Match", back_populates="listing")
    viewing_requests = relationship("ViewingRequest", back_populates="listing")
    payments = relationship("ListingPayment", back_populates="listing")


class ListingMedia(Base):
    __tablename__ = "listing_media"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(
        Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    media_type = Column(String(20), default="image")  # image|video|floor_plan|virtual_tour
    url = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    listing = relationship("Listing", back_populates="media")


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("buyer_id", "listing_id", name="uq_buyer_listing"),
    )

    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    opened = Column(Boolean, default=False)
    interested = Column(Boolean)          # None=no reply, True=liked, False=skipped
    skipped = Column(Boolean, default=False)
    viewing_requested = Column(Boolean, default=False)

    buyer = relationship("Buyer", back_populates="matches")
    listing = relationship("Listing", back_populates="matches")
    viewing_requests = relationship("ViewingRequest", back_populates="match")


class ViewingRequest(Base):
    __tablename__ = "viewing_requests"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("buyers.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    status = Column(String(20), default="pending")   # pending|confirmed|cancelled|completed
    preferred_date = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    match = relationship("Match", back_populates="viewing_requests")
    buyer = relationship("Buyer", back_populates="viewing_requests")
    listing = relationship("Listing", back_populates="viewing_requests")
    agent = relationship("Agent", back_populates="viewing_requests")


class ListingPayment(Base):
    __tablename__ = "listing_payments"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    stripe_payment_id = Column(String(255))
    amount = Column(Float)
    status = Column(String(20), default="pending")  # pending|paid|failed|refunded
    paid_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listing = relationship("Listing", back_populates="payments")
    agent = relationship("Agent", back_populates="payments")
