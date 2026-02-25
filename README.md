# RESCU - Rapid Emergency Sensor Communications Unit
Team: Reed B., Alexis H., Ishana T., Haejune K, Jacob H.

Family members often worry about the safety of older and elderly family members who live alone. One of the most significant risks faced by the elderly population is fall-induced injury, as falls are the leading cause of both fatal and nonfatal injuries among older adults. Mobility-related challenges become worse with age, which leads to this increased risk of falling for the elderly population. As a result, families want a proper and reliable safety net in place to protect their elderly family members that live alone. 

Currently, medical alert devices are the most common solution for this safety net. These devices detect when a user has fallen and notify the proper emergency medical services. However, the options available currently on the market are extremely inconsistent, expensive, and confusing to set up.  

To address these problems, we are proposing an app-paired safety device that consistently monitors the fall status of our users and then contacts the user’s prechosen emergency contacts upon a fall event. Our device will offer a wider range of customization options, ease of setup, and affordability to make sure that our users and their families can have the peace of mind that they desire with their safety net. In this customization, the user will be able to input a list of emergency contacts that will be contacted in priority order that the user chooses. Additionally, since our device will pair with the user’s mobile phone, the device will be able to be used both indoors and outdoors, which is an advantage over other market-available options.  

As for the aspects and components of our system, we are proposing a wearable arm band that contacts a microcontroller, an inertial measurement unit (IMU), and a barometer. The IMU and barometer will both be used for fall detection, to determine when rapid acceleration, orientation changes, and impact events associated with falls. The microcontroller will process this data from the sensors, determine if a fall has occurred, and then notify the mobile application if a fall event has occurred. The phone application will contact pre-selected emergency contacts when a fall event has occurred, and the user is in danger.  

**Notes for Devs**
Before opening a pull request:
- Run flake8
- Run black .
- Run pytest

*Developed as a part of Purdue University ECE Senior Design*