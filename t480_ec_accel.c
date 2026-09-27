// SPDX-License-Identifier: WTFPL
/* N24HT37W two-axis base accelerometer. No EC debug key or firmware writes.
 * Host mailbox: MEC BAR FF3364=16108001, index/data ports 1610/1611.
 * This is deliberately restricted to the T480 + EC combination.
 */
#include <linux/acpi.h>
#include <linux/delay.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/io.h>
#include <linux/ioport.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/suspend.h>
#include <linux/unaligned.h>

#define EC_LOCK "\\_SB.PCI0.LPCB.EC.ECLK"
#define MB_PORT 0x1610
#define NAME "ThinkPad T480 EC accelerometer"
static DEFINE_MUTEX(sensor_lock);
static struct input_dev *sensor;
static bool opened, suspended, owned;
static bool active;
static bool probe_only = true;
module_param(probe_only, bool, 0444);
MODULE_PARM_DESC(probe_only, "Query status only; do not register an input device or start acquisition");
static int last_error;
static unsigned long samples;
static unsigned int warmup;
module_param(active, bool, 0444);
MODULE_PARM_DESC(active, "Acquisition started successfully (not a physical rail measurement)");
module_param(last_error, int, 0444);
module_param(samples, ulong, 0444);
/* Only recover/ack a timed-out command which this driver itself issued. */
static u8 pending;
static u8 mb_read(u8 index)
{
 outb(index, MB_PORT);
 return inb(MB_PORT + 1);
}
static void mb_write(u8 index, u8 value)
{
 outb(index, MB_PORT);
 outb(value, MB_PORT + 1);
}
static int await_response(u8 command)
{
 int i;
 for (i = 0; i < 100; i++) {
  if (!mb_read(0) && mb_read(1) == command)
   return 0;
  usleep_range(5000, 6000);
 }
 return -ETIMEDOUT;
}
/* Caller holds sensor_lock; ACPI clients use ECLK around each transaction.
 * N24HT37W command 11 is output-only: EC dispatch 2c5dc/2c9e2 overwrites
 * the response without consuming payload arguments. N24HT37W handler builds its response from the sensor ring.
 * See PROTOCOL.md for the firmware trace.
 * Other commands preserve payload; successful transactions restore the index.
 * Timeout leaves buffers/index alone while the EC may still be using them.
 */
static int mailbox(u8 command, u32 argument, u8 *reply)
{
 u8 saved[32], index;
 bool output_only = command == 0x11;
 int i, ret;
 if (ACPI_FAILURE(acpi_acquire_mutex(NULL, EC_LOCK, 1000)))
  return -EBUSY;
 index = inb(MB_PORT);
 if (pending) {
  ret = await_response(pending);
  if (ret)
   goto unlock;
  mb_write(1, 0xff);
  pending = 0;
 }
 if (mb_read(0) || mb_read(1)) {
  ret = -EBUSY;
  goto restore_index;
 }
 if (!output_only) {
  for (i = 0; i < 32; i++)
   saved[i] = mb_read(0x10 + i);
  for (i = 0; i < 32; i++)
   mb_write(0x10 + i, i < 4 ? argument >> (8 * i) : 0);
 }
 pending = command;
 mb_write(0, command);
 ret = await_response(command);
 if (ret)
  goto unlock;
 for (i = 0; i < 32; i++)
  reply[i] = mb_read(0x10 + i);
 mb_write(1, 0xff);
 pending = 0;
 if (!output_only)
  for (i = 0; i < 32; i++)
   mb_write(0x10 + i, saved[i]);
restore_index:
 outb(index, MB_PORT);
unlock:
 acpi_release_mutex(NULL, EC_LOCK);
 return ret;
}
static int stop_sensor(void)
{
 u8 data[32];
 int ret = 0, i;
 active = false;
 if (!owned)
  return 0;
 for (i = 0; i < 3; i++) {
  ret = mailbox(0x10, 0, data);
  if (!ret)
   ret = mailbox(0x14, 0, data);
  if (!ret) {
   msleep(50);
   ret = mailbox(0x17, 0x82, data);
   if (!ret && (data[0] || data[31]))
    ret = -EBUSY;
  }
  if (!ret) {
   owned = false;
   return 0;
  }
 }
 last_error = ret;
 pr_err("t480_ec_accel: could not confirm sensor shutdown: %d\n", ret);
 return ret;
}
static int start_sensor(void)
{
 u8 data[32];
 int ret;
 if (owned) {
  ret = stop_sensor();
  if (ret)
   return ret;
 }
 ret = mailbox(0x17, 0x82, data);
 if (ret)
  return ret;
 if (data[31])
  return -EIO;
 /* Do not take over sampling or self-test started by another client. */
 if (data[0] || data[31])
  return -EBUSY;
 owned = true; /* A power-enable timeout still needs cleanup. */
 ret = mailbox(0x14, 1, data);
 if (!ret && get_unaligned_le32(data + 28))
  ret = -EIO;
 if (ret)
  goto fail;
 msleep(100);
 ret = mailbox(0x10, 0x0a0200c8, data);
 if (!ret && data[31])
  ret = -EIO;
 if (ret)
  goto fail;
 msleep(50);
 ret = mailbox(0x17, 0x82, data);
 if (!ret && (!(data[0] & 1) || data[31]))
  ret = -EIO;
 if (ret)
  goto fail;
 warmup = 2; /* Discard startup ring contents before reporting fresh axes. */
 active = true;
 last_error = 0;
 return 0;
fail:
 stop_sensor();
 return ret;
}
static void poll_sensor(struct input_dev *dev)
{
 u8 data[32];
 unsigned int x = 0, y = 0, i;
 int ret;
 mutex_lock(&sensor_lock);
 if (!active || suspended)
  goto out;
 ret = mailbox(0x11, 0, data);
 if (!ret && (data[0] > 5 || data[31]))
  ret = -EPROTO;
 if (ret) {
  last_error = ret;
  pr_err_ratelimited("t480_ec_accel: acquisition failed: %d\n", ret);
  stop_sensor();
  goto out;
 }
 if (warmup) {
  warmup--;
  goto out;
 }
 if (!data[0])
  goto out;
 for (i = 0; i < data[0]; i++) {
  x += get_unaligned_le16(data + 1 + i * 5);
  y += get_unaligned_le16(data + 3 + i * 5);
 }
 input_report_abs(dev, ABS_X, x / data[0]);
 input_report_abs(dev, ABS_Y, y / data[0]);
 /* Heartbeat permits stale-data detection even when ABS values don't change.
  * This is host receipt time, not an EC hardware acquisition timestamp.
  */
 input_event(dev, EV_MSC, MSC_TIMESTAMP, (u32)ktime_to_us(ktime_get()));
 input_sync(dev);
 samples++;
out:
 mutex_unlock(&sensor_lock);
}
static int open_sensor(struct input_dev *dev)
{
 int ret;
 mutex_lock(&sensor_lock);
 ret = suspended ? -EBUSY : start_sensor();
 if (!ret)
  opened = true;
 else
  last_error = ret;
 mutex_unlock(&sensor_lock);
 return ret;
}
static void close_sensor(struct input_dev *dev)
{
 mutex_lock(&sensor_lock);
 opened = false;
 stop_sensor();
 mutex_unlock(&sensor_lock);
}
static int power_event(struct notifier_block *nb, unsigned long event, void *arg)
{
 int ret = 0;
 mutex_lock(&sensor_lock);
 switch (event) {
 case PM_SUSPEND_PREPARE:
 case PM_HIBERNATION_PREPARE:
 case PM_RESTORE_PREPARE:
  suspended = true;
  ret = stop_sensor();
  break;
 case PM_POST_SUSPEND:
 case PM_POST_HIBERNATION:
 case PM_POST_RESTORE:
  suspended = false;
  if (opened) {
   ret = start_sensor();
   if (ret) {
    last_error = ret;
    pr_err("t480_ec_accel: resume failed: %d\n", ret);
   }
  }
  ret = 0; /* Resume failure is handled by the consumer's stale timeout. */
  break;
 }
 mutex_unlock(&sensor_lock);
 return ret ? NOTIFY_BAD : NOTIFY_OK;
}
static struct notifier_block pm_notifier = { .notifier_call = power_event };
static int __init accel_init(void)
{
 u8 fw[8];
 int i, ret = 0;
 if (!dmi_match(DMI_PRODUCT_VERSION, "ThinkPad T480") &&
     !dmi_match(DMI_PRODUCT_NAME, "ThinkPad T480") &&
     !dmi_match(DMI_PRODUCT_NAME, "T480"))
  return -ENODEV;
 if (ACPI_FAILURE(acpi_acquire_mutex(NULL, EC_LOCK, 1000)))
  return -EBUSY;
 for (i = 0; i < 8; i++) {
  ret = ec_read(0xf0 + i, &fw[i]);
  if (ret)
   break;
 }
 acpi_release_mutex(NULL, EC_LOCK);
 if (ret || memcmp(fw, "N24HT37W", 8))
  return -ENODEV;
 /* PNP motherboard resources are non-busy containers. Claim only these two
  * ports as their child; never remove reservations or touch EC3 at 1618.
  */
 if (!request_region(MB_PORT, 2, "t480_ec_accel"))
  return -EBUSY;
 if (probe_only) {
  u8 data[32];
  mutex_lock(&sensor_lock);
  ret = mailbox(0x17, 0x82, data);
  mutex_unlock(&sensor_lock);
  if (!ret)
   pr_info("t480_ec_accel: N24HT37W status=%02x rate=%u filter=%u error=%02x (probe only)\n",
           data[0], get_unaligned_le16(data + 1), data[3], data[31]);
  else
   pr_err("t480_ec_accel: status probe failed: %d\n", ret);
  release_region(MB_PORT, 2);
  return ret;
 }
 sensor = input_allocate_device();
 if (!sensor) {
  ret = -ENOMEM;
  goto release;
 }
 sensor->name = NAME;
 sensor->phys = "t480-ec/mailbox0";
 sensor->id.bustype = BUS_HOST;
 sensor->open = open_sensor;
 sensor->close = close_sensor;
 __set_bit(INPUT_PROP_ACCELEROMETER, sensor->propbit);
 input_set_abs_params(sensor, ABS_X, 0, 65535, 0, 0);
 input_set_abs_params(sensor, ABS_Y, 0, 65535, 0, 0);
 input_set_capability(sensor, EV_MSC, MSC_TIMESTAMP);
 ret = input_setup_polling(sensor, poll_sensor);
 if (ret)
  goto free;
 input_set_poll_interval(sensor, 500);
 input_set_min_poll_interval(sensor, 200);
 input_set_max_poll_interval(sensor, 2000);
 ret = register_pm_notifier(&pm_notifier);
 if (ret)
  goto free;
 ret = input_register_device(sensor);
 if (ret) {
  unregister_pm_notifier(&pm_notifier);
  goto free;
 }
 pr_info("t480_ec_accel: N24HT37W raw X/Y sensor registered; power on demand\n");
 return 0;
free:
 input_free_device(sensor);
release:
 release_region(MB_PORT, 2);
 return ret;
}
static void __exit accel_exit(void)
{
 if (probe_only)
  return;
 unregister_pm_notifier(&pm_notifier);
 input_unregister_device(sensor);
 mutex_lock(&sensor_lock);
 stop_sensor();
 mutex_unlock(&sensor_lock);
 release_region(MB_PORT, 2);
}
module_init(accel_init);
module_exit(accel_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("N24HT37W ThinkPad EC raw two-axis accelerometer");
