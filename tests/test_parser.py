from types import SimpleNamespace
from src.bloodhound.parser import parse_post
from src.bloodhound.models import PostType

def make_msg(text, msg_id=1):
    return SimpleNamespace(id=msg_id, message=text)


def test_parse_rent_post():
    text = "#Vake 🚇 #Rustaveli\n🏢 #1Bed Apartment for #Rent\n🏠 75 Sq.m | 10 Floor |\n💰 800$"
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 800
    assert post.rooms == 1  # '#1Bed' -> 1
    assert post.district == "Vake"

def test_real_post1():
    text = """#Vake 🚇 #Rustaveli
📍1 Tskneti Hwy

🏢 #2Bed Apartment for #Rent 
✨ #NewBuilding | #New
🏠100 Sq.m | 9 Floor 
#CentralHeating #Shower 

✅#Conditioner ✅#Oven ✅#Stove ✅#WiFi ✅#Balcony ✅#TV 
✅#Microwave

✖️Dishwasher

👬Tenants: 1-2
🐕Pets: #ByAgreement
🕐 #6Month #12Month 

💰750$ + Deposit 750$ | 
 0% Commission
#Price700to900

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Sergi
🌟 Check all listings | Reviews

📷 Instagram 🗳️ FB 🎥 YouTube"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 750
    assert post.rooms == 2
    assert post.district == "Vake"
    assert post.metro == "Rustaveli"
    assert post.address == "1 Tskneti Hwy"
    assert post.floor == 9
    assert post.size_sqm == 100
    assert post.pets == "by_agreement"
    assert "Oven" in post.features
    assert "Conditioner" in post.features
    assert "Dishwasher" not in post.features

def test_ignore_rented():
    text = "❗️#Rented\nNice apartment in 📍Vake found a tenant 🤝👏🎉"
    post = parse_post(make_msg(text, msg_id=101), channel_id="12345")
    assert post is None


def test_ignore_incomplete():
    text = "Just some random text without tags or structured info"
    post = parse_post(make_msg(text, msg_id=102), channel_id="12345")
    assert post is None

def test_real_post_sell_1():
    text = """#Saburtalo 🚇 #TCUniversity
📍39 Bakhtrioni Street

🏢 #1Bed Apartment for #Sell
✨ #OldBuilding | #New
🏠55 Sq.m | 2 Floor | 
#CentralHeating | #Shower

✅#Conditioner ✅#Oven ✅#Stove ✅#WiFi ✅#Balcony ✅#TV 

✖️Dishwasher ✖️Microwave 

💰 100.000$| 
 0% Commission
#Price90000to120000

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Sergi
🌟 Check all listings | Reviews

📷 Instagram 🗳 FB 🎥 YouTube

SALE IN TBILISI🇬🇪
"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.sell
    assert post.price == 100000
    assert post.rooms == 1
    assert post.district == "Saburtalo"
    assert post.metro == "TCUniversity"
    assert post.address == "39 Bakhtrioni Street"
    assert post.floor == 2
    assert post.size_sqm == 55
    assert post.pets is None



def test_real_post_rent_3():
    text = """#Saburtalo 🚇  #Delisi📍2 Giorgi Gegechkori St

🏢 #2Bed Apartment for #Rent
✨ #OldBuilding | #Mixed
🏠 86 Sq.m | 4 Floor |
#CentralHeating | #Shower
  
✅ #Stove ✅#Oven
✅ #TV ✅ #WiFi 
✅ #VacuumCleaner
✅ #Balcony
✅ #Conditioner

✖️Elevator
✖️Dishwasher

👬Tenants: 1-4
🐕 Pets: #ByAgreement
🕐 #6Month #12Month

💰 800$ + Deposit 800$
0% Commission
#Price700to900 

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Giga
🌟 Check all listings | Reviews

📷 Instagram 🗳 FB 🎥 YouTube
"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 800
    assert post.rooms == 2
    assert post.district == "Saburtalo"
    assert post.metro == "Delisi"
    assert post.address == "2 Giorgi Gegechkori St"
    assert post.floor == 4
    assert post.size_sqm == 86
    assert post.pets == "by_agreement"

def test_real_post_rent_4():
    text = """#Chugureti 🚇 #StationSquare 📍68 Giorgi Chubinashvili street

🌳 In M2 Complex 

🏢 #1Bed Apartment for #Rent
✨ #NewBuilding | #Mixed
🏠 75 Sq.m | 2 Floor | #CentralHeating | #Shower

✅ #TV  ✅ #WiFi ✅ #Oven
✅ #Stove ✅ #Conditioner 
✅ #VacuumCleaner
✅ #Microwave ✅ #Balcony
✅ #Elevator
✅ #ParkingPlace

✖️Dishwasher

👫 Tenants: 1-2
🐕 Pets: #ByAgreement (small)
🕐 #6Month #12Month

💰 650$$ + Deposit 650$
0% Commission
#Price500to700

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Irakli 
🌟 Check all listings | Reviews

📷 Instagram 🗳 FB 🎥 YouTube"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 650
    assert post.rooms == 1
    assert post.district == "Chugureti"
    assert post.metro == "StationSquare"
    assert post.address == "68 Giorgi Chubinashvili street"
    assert post.floor == 2
    assert post.size_sqm == 75
    assert post.pets is "by_agreement"

def test_real_post_sell_2():
    text = """#Vera  🚇 #Rustaveli 
📍8 Vasil Petriashvili St

🏢 #2Bed Apartment for #Sale 
✨ Historical #Oldbuilding | #Retro
🏠63 Sq.m | 1 Floor 

✅#Bath ✅#WiFi ✅#Stove ✅#TV ✅Piano

✖️Conditioner ✖️Balcony
✖️Central Heating

💰235.000$
#Price210000to240000

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Alex
🌟 Check all listings | Reviews
📷 Instagram 🗳️ FB 🎥 YouTube"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.sell
    assert post.price == 235000
    assert post.rooms == 2
    assert post.district == "Vera"
    assert post.metro == "Rustaveli"
    assert post.address == "8 Vasil Petriashvili St"
    assert post.floor == 1
    assert post.size_sqm == 63

def test_real_post_rent_5():
    text = """#Saburtalo 🚇#Delisi             
📍Park Home Delisi    

All New apartment with Cozy Interior & City View - No one Lived ❗️

🏢 #2Bed Apartment for #Rent 
✨ #NewBuilding | #New 
🏠 50 Sq.m | 13 Floor | #CentralHeating | #Shower

✅#WiFi
✅#Balcony ✅#Conditioner 2 ✅#Oven ✅#SmartTV 

💰700$ + Deposit 700$ | 
 0% Commission 
#Price500to700
#Price700to900 

👬Tenants: 1-2
🐕Pets: #Allowed (Deposit)
🕐 #12Month 

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Shafi
🌟 Check all listings | Reviews

📷 Instagram 🗳 FB 🎥 YouTube"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 700
    assert post.rooms == 2
    assert post.district == "Saburtalo"
    assert post.metro == "Delisi"
    assert post.address == "Park Home Delisi"
    assert post.floor == 13
    assert post.size_sqm == 50
    assert post.pets is "allowed"
    assert "WiFi" in post.features
    assert "Balcony" in post.features
    assert "Conditioner" in post.features
    assert "Oven" in post.features
    assert "SmartTV" in post.features

def test_real_post_sell_6():
    text = """#Vera 🚇 #Libertysquare  
📍11 Lado Gudiashvili  

⭐️⭐️EXCLUSIVE SALE – A Unique Property in the Heart of Tbilisi!⭐️⭐️

🏢 #1Bed Apartment for #Sale
✨ #HistoricalBuilding | #Old
🏠 54.9 Sq.m | 2Floor | #Bath

Prime Location:
✅ 2 min from Liberty Square
✅ 1 min to Parliament of Georgia
✅ 3 min to Dry Bridge & 
✅ Opposite to Alexander Park 🌲

🏡 Perfect for:
✅#Office ✅#Cafe ✅#Investment ✅#Airbnb ✅#HistoricalValue ✅#Showroom

💡 Only a renovation is needed to turn this into the perfect living space or high-income rental!

💰 110.000$ | 
0% Commission
#Price90000to120000

📲 @David_Tibelashvili |
+995 599 20 67 16 #Shafi
🌟 Check all listings | Reviews

📷 Instagram 🗳️ FB 🎥 YouTube

 SALE IN TBILISI🇬🇪"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.sell
    assert post.price == 110000
    assert post.rooms == 1
    assert post.district == "Vera"
    assert post.metro == "LibertySquare"
    assert post.address == "11 Lado Gudiashvili"
    assert post.floor == 2
    assert post.size_sqm == 54.9

def test_real_post_rent_6():
    text = """#Vake 🚇 #Rustaveli
📍82 Irakli Abashidze Street

🪴Near Vake Park

🏢 #3Bed Apartment for #Rent 
✨  #OldBuilding| #Mixed 
🏠200 Sq.m | 2 Floor | #CentralHeating

✅#Balcony (2) ✅#WiFi 
✅#Stove ✅#Microwave
✅#Oven ✅#Conditioner (2)
✅#Dishwasher ✅#TV 

✖️ParkingPlace ✖️Elevator

👬Tenants: 1-6
🐕Pets: #ByAgreement
🕐 #6Month #12Month 

💰 $1500 + Deposit $1500 | 
 0% Commission
#Price1200plus

📲 @David_Tibelashvili | 
+995 599 20 67 16 #Vlad
🌟 Check all listings | Reviews

📷 Instagram 🗳 FB 🎥 YouTube"""
    post = parse_post(make_msg(text, msg_id=100), channel_id="12345")
    assert post is not None
    assert post.type == PostType.rent
    assert post.price == 1500
    assert post.rooms == 3
    assert post.district == "Vake"
    assert post.metro == "Rustaveli"
    assert post.address == "82 Irakli Abashidze Street"
    assert post.floor == 2
    assert post.size_sqm == 200
    assert "Balcony" in post.features