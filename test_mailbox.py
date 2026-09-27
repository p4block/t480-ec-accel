# SPDX-License-Identifier: WTFPL
"""Compile the actual mailbox functions against a deterministic EC/port model."""
import pathlib,subprocess,tempfile,unittest

class Mailbox(unittest.TestCase):
    def test_output_only_control_busy_timeout_and_recovery(self):
        source=(pathlib.Path(__file__).parent/'t480_ec_accel.c').read_text()
        funcs=source[source.index('static u8 pending;'):source.index('static int stop_sensor(')]
        harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define MB_PORT 0x1610
#define EC_LOCK "test"
#define ACPI_FAILURE(x) (x)
static u8 regs[256], index_reg, command_payload[32];
static int writes, commands, acks, locks, timeout_mode, sleeps;
static int acpi_acquire_mutex(void *a,const char*b,int c){ locks++;return 0; }
static void acpi_release_mutex(void*a,const char*b){ locks--; }
static u8 inb(int port){return port==MB_PORT?index_reg:regs[index_reg];}
static void outb(u8 v,int port){
 if(port==MB_PORT){index_reg=v;return;}
 if(index_reg>=0x10 && index_reg<0x30)writes++;
 if(index_reg==1 && v==0xff){acks++;regs[1]=0;return;}
 regs[index_reg]=v;
 if(index_reg==0 && v){
  commands++;memcpy(command_payload,regs+0x10,32);
  if(!timeout_mode){for(int i=0;i<32;i++)regs[0x10+i]=i+1;regs[0]=0;regs[1]=v;}
 }
}
static void usleep_range(int a,int b){sleeps++;}
'''+funcs+r'''
static void reset(void){
 memset(regs,0,sizeof(regs));for(int i=0;i<32;i++)regs[0x10+i]=0xa0+i;
 index_reg=7;writes=commands=acks=locks=timeout_mode=sleeps=0;pending=0;
}
int main(void){
 u8 reply[32],original[32];int ret;
 reset();memcpy(original,regs+0x10,32);
 ret=mailbox(0x11,0,reply);
 assert(!ret && writes==0 && commands==1 && acks==1 && !locks && !pending);
 assert(index_reg==7 && !memcmp(command_payload,original,32));
 for(int i=0;i<32;i++)assert(reply[i]==i+1);
 reset();memcpy(original,regs+0x10,32);
 ret=mailbox(0x17,0x82,reply);
 assert(!ret && writes==64 && commands==1 && acks==1 && !locks && !pending);
 assert(command_payload[0]==0x82 && command_payload[1]==0);
 assert(!memcmp(regs+0x10,original,32) && index_reg==7);
 reset();regs[0]=0x14;
 assert(mailbox(0x11,0,reply)==-EBUSY && !commands && !writes && index_reg==7 && !locks);
 reset();timeout_mode=1;
 assert(mailbox(0x11,0,reply)==-ETIMEDOUT);
 assert(commands==1 && acks==0 && writes==0 && pending==0x11 && sleeps==100 && !locks);
 // Still pending: do not issue another command, overwrite or acknowledge it.
 assert(mailbox(0x11,0,reply)==-ETIMEDOUT && commands==1 && !acks && !writes);
 // The owned command finishes; next call may acknowledge/recover it.
 timeout_mode=0;regs[0]=0;regs[1]=0x11;
 assert(!mailbox(0x11,0,reply) && commands==2 && acks==2 && !pending && !locks);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);(p/'test.c').write_text(harness)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True)
