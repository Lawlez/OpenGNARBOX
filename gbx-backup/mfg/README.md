# Manufacturing tools and tests.

Tools in ./tools
Functional tests in ./tests/functional
Smoke tests in ./tests/smoke

# Testing

The tests are run by firstboot-test.service, which runs
/sbin/firstboot-test.  On first boot there are no test latch files.  This
causes firstboot-test to enter functional test mode.  After successful
functional tests the test_cleanup script creates a latch file.  On the
next boot this latch file causes firstboot-test to enter smoke test mode.
After successful smoke tests firstboot-test creates another latch file
and disables firstboot-test.service.  The next boot is a standard boot.
If either suite of tests fail, then no latchfile is created and the next
boot will remain in the given test mode to be retested.

# Tools

- tools/flasher
	- Script used on SSD flashing station to flash SSDs and add them
	to SQL database.

- tools/gbx-sn
- tools/ssd-sn
	- Read the gbx or ssd serial number from the eeprom.

- tools/key_press.c
	- Read a single keypress and print it to stdout.

- tools/mender-preauthorize
	- Given a serial number and public key, preauthorize a device
	with the mender server.

- tools/read-eeprom
	- Helper script to read a nul terminated string from the eeprom.

# Functional Tests

- tests/functional/test_cleanup
	- Creates the functional test latch file so smoke tests start on next boot.

- tests/functional/eeprom_test <gbx_serial_number> <ssd_serial_number>
	- Writes gbx and ssd serial numbers to the eeprom and reads them
	back to verify.

- tests/functional/key_test
	- Verifies that all of the Gnarbox button keys are working
	correctly.  Runs key_test_forever with a timeout. Requires
	user interaction.

- tests/functional/key_test_forever
	- Helper script that does the actual key test.

- tests/functional/mender_device_key
	- Creates an authentication key pair for Mender and returns the
	public key in the form 'MENDER_PUBLIC_KEY=<value>'.

- tests/functional/oled_test
	- Verifies that the Gnarbox OLED does not have any dead or
	stuck pixels.  Requires operator interaction.

- tests/functional/ram_test
	- Verifies that the Gnarbox reports having the correct amount
	of RAM.

- tests/functional/sd_card_test
	- Generates a file and copies to SD Card. Reads back to verify.
	Removes file on cleanup.

- tests/functional/ssd_serial
	- Reads SSD serial number and returns it in the form 'SSD_SERIAL=<value>'

- tests/functional/ssd_size_gb
	- Reads SSD size in GB and returns it in the form 'SSD_SIZE_GB=<value>'

- tests/functional/ssid_test
	- Edits the ssid in /app_data/hostapd/hostapd.conf and 
        /etc/hostapd.conf to include the serial number.

- tests/functional/storage_test
	- Helper script run by sd_card_test and usb_test.

- tests/functional/thermal_test
	- Verifies that the Gnarbox thermister sensors are reporting
	temperature values within acceptable range.

- tests/functional/time_date_test
	- Set the time and date.  Many formats accepted.  Any timezone
	can be used, will be translated correctly.

- tests/functional/usb_test
	- Generates a file and copies to SD Card. Reads back to verify.
	Removes file on cleanup.

- tests/functional/version_app
	- Reads app version from the installed app stack and returns it 
	in the form 'VERSION_APP=<value>'

- tests/functional/version_os
	- Reads os version and returns it in the form 'VERSION_OS=<value>'

- tests/functional/wifi_test
	- Verifies that the Gnarbox Wifi module can scan for 2.4GHz and
	5GHz networks.

- tests/functional/ssd_firmware
	- Verifies that the SSD is running the expected firmware version.
	If the SSD is not running the expected firmware version, the test
	will attempt to update the firmware.

# Smoke Tests

- tests/smoke/smoke_test
	- Runs the suite of smoke tests, printing pass or fail status
	to stdout and OLED.

- tests/smoke/battery_test
	- Reads the battery temperature to ensure communication with
	the PCM.
