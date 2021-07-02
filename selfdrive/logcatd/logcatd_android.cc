#include <sys/time.h>
#include <sys/resource.h>

#include <android/log.h>
#include <log/logger.h>
#include <log/logprint.h>

#include "cereal/messaging/messaging.h"
#include "selfdrive/common/util.h"
#include "selfdrive/common/params.h"


// atom
typedef struct LiveMapDataResult {
      float speedLimit;  // Float32;
      float speedLimitDistance;  // Float32;
      float safetySign;    // Float32;
      float roadCurvature;    // Float32;
      bool  mapValid;    // bool;
      bool  mapEnable;    // bool;
} LiveMapDataResult;


int main() {
  setpriority(PRIO_PROCESS, 0, -15);

  int     nTime = 0;
  ExitHandler do_exit;
  PubMaster pm({"liveMapData"});
  LiveMapDataResult res;

  log_time last_log_time = {};
  logger_list *logger_list = android_logger_list_alloc(ANDROID_LOG_RDONLY | ANDROID_LOG_NONBLOCK, 0, 0);

  while (!do_exit) {
    // setup android logging
    if (!logger_list) {
      logger_list = android_logger_list_alloc_time(ANDROID_LOG_RDONLY | ANDROID_LOG_NONBLOCK, last_log_time, 0);
    }
    assert(logger_list);

    struct logger *main_logger = android_logger_open(logger_list, LOG_ID_MAIN);
    assert(main_logger);
   // struct logger *radio_logger = android_logger_open(logger_list, LOG_ID_RADIO);
   // assert(radio_logger);
   // struct logger *system_logger = android_logger_open(logger_list, LOG_ID_SYSTEM);
   // assert(system_logger);
   // struct logger *crash_logger = android_logger_open(logger_list, LOG_ID_CRASH);
   // assert(crash_logger);
   // struct logger *kernel_logger = android_logger_open(logger_list, (log_id_t)5); // LOG_ID_KERNEL
   // assert(kernel_logger);

    while (!do_exit) {
      log_msg log_msg;
      int err = android_logger_list_read(logger_list, &log_msg);
      if (err <= 0) break;

      AndroidLogEntry entry;
      err = android_log_processLogBuffer(&log_msg.entry_v1, &entry);
      if (err < 0) continue;
      last_log_time.tv_sec = entry.tv_sec;
      last_log_time.tv_nsec = entry.tv_nsec;

      nTime++;
      if( nTime > 10 )
      {
        nTime = 0;
        res.mapEnable = Params().getBool("OpkrMapEnable");
      }
      
      res.mapValid = Params().getBool("OpkrApksEnable");

      MessageBuilder msg;
      auto framed = msg.initEvent().initLiveMapData();

   //  opkrspdlimit, opkrspddist, opkrsigntype, opkrcurvangle
/*
   opkrsigntype 값정리

*/
      // code based from atom
      if( strcmp( entry.tag, "opkrspddist" ) == 0 )
      {
        res.speedLimitDistance = atoi( entry.message );
      }
      else if( strcmp( entry.tag, "opkrspdlimit" ) == 0 )
      {
        res.speedLimit = atoi( entry.message );
      }
      else if( strcmp( entry.tag, "opkrcurvangle" ) == 0 )
      {
        res.roadCurvature = atoi( entry.message );
      }
      else if( strcmp( entry.tag, "opkrsigntype" ) == 0 )
      {
        res.safetySign = atoi( entry.message );
      }

      framed.setSpeedLimit( res.speedLimit );  // Float32;
      framed.setSpeedLimitDistance( res.speedLimitDistance );  // raw_target_speed_map_dist Float32;
      framed.setSafetySign( res.safetySign ); // map_sign Float32;
      framed.setRoadCurvature( res.roadCurvature ); // road_curvature Float32;

      framed.setMapEnable( res.mapEnable );
      framed.setMapValid( res.mapValid );
      
      
     // if( opkr )
     // {
     // printf("logcat ID(%d) - PID=%d tag=%d.[%s] \n", log_msg.id(), entry.pid,  entry.tid, entry.tag);
     // printf("entry.message=[%s]\n", entry.message);
     // printf("spd = %f\n", res.speedLimit );
     // }

      pm.send("liveMapData", msg);
    }

    android_logger_list_free(logger_list);
    logger_list = NULL;
    util::sleep_for(500);
  }

  if (logger_list) {
    android_logger_list_free(logger_list);
  }

  return 0;
}
