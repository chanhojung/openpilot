#include "selfdrive/ui/qt/home.h"

#include <QDate>
#include <QDateTime>
#include <QHBoxLayout>
#include <QMouseEvent>
#include <QVBoxLayout>
#include <QProcess> // opkr

#include "selfdrive/common/params.h"
#include "selfdrive/common/swaglog.h"
#include "selfdrive/common/timing.h"
#include "selfdrive/common/util.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/drive_stats.h"
#include "selfdrive/ui/qt/widgets/setup.h"

// HomeWindow: the container for the offroad and onroad UIs

HomeWindow::HomeWindow(QWidget* parent) : QWidget(parent) {
  QHBoxLayout *main_layout = new QHBoxLayout(this);
  main_layout->setMargin(0);
  main_layout->setSpacing(0);

  sidebar = new Sidebar(this);
  main_layout->addWidget(sidebar);
  QObject::connect(this, &HomeWindow::update, sidebar, &Sidebar::updateState);
  QObject::connect(sidebar, &Sidebar::openSettings, this, &HomeWindow::openSettings);

  slayout = new QStackedLayout();
  main_layout->addLayout(slayout);

  onroad = new OnroadWindow(this);
  slayout->addWidget(onroad);

  QObject::connect(this, &HomeWindow::update, onroad, &OnroadWindow::update);
  QObject::connect(this, &HomeWindow::offroadTransitionSignal, onroad, &OnroadWindow::offroadTransitionSignal);

  home = new OffroadHome();
  slayout->addWidget(home);

  driver_view = new DriverViewWindow(this);
  connect(driver_view, &DriverViewWindow::done, [=] {
    showDriverView(false);
  });
  slayout->addWidget(driver_view);
}

void HomeWindow::showSidebar(bool show) {
  sidebar->setVisible(show);
}

void HomeWindow::offroadTransition(bool offroad) {
  if (offroad) {
    slayout->setCurrentWidget(home);
  } else {
    slayout->setCurrentWidget(onroad);
  }
  sidebar->setVisible(offroad);
  emit offroadTransitionSignal(offroad);
}

void HomeWindow::showDriverView(bool show) {
  if (show) {
    emit closeSettings();
    slayout->setCurrentWidget(driver_view);
  } else {
    slayout->setCurrentWidget(home);
  }
  sidebar->setVisible(show == false);
}

void HomeWindow::mousePressEvent(QMouseEvent* e) {
  // OPKR add map
  if (QUIState::ui_state.scene.apks_enabled && QUIState::ui_state.scene.started && map_overlay_btn.ptInRect(e->x(), e->y())) {
    QSoundEffect effect1;
    effect1.setSource(QUrl::fromLocalFile("/data/openpilot/selfdrive/assets/sounds/warning_1.wav"));
    //effect1.setLoopCount(1);
    //effect1.setLoopCount(QSoundEffect::Infinite);
    //effect1.setVolume(0.1);
    effect1.play();
    QProcess::execute("am start --activity-task-on-home com.opkr.maphack/com.opkr.maphack.MainActivity");
    QUIState::ui_state.scene.map_on_top = false;
    QUIState::ui_state.scene.map_on_overlay = true;
    return;
  }
  if (QUIState::ui_state.scene.apks_enabled && QUIState::ui_state.scene.started && !sidebar->isVisible() && !QUIState::ui_state.scene.map_on_top && map_btn.ptInRect(e->x(), e->y())) {
    QSoundEffect effect2;
    effect2.setSource(QUrl::fromLocalFile("/data/openpilot/selfdrive/assets/sounds/warning_1.wav"));
    //effect2.setLoopCount(1);
    //effect2.setLoopCount(QSoundEffect::Infinite);
    //effect2.setVolume(0.1);
    effect2.play();
    QUIState::ui_state.scene.map_is_running = !QUIState::ui_state.scene.map_is_running;
    if (QUIState::ui_state.scene.map_is_running) {
      QProcess::execute("am start com.mnsoft.mappyobn/com.mnsoft.mappy.MainActivity");
      QUIState::ui_state.scene.map_on_top = true;
      QUIState::ui_state.scene.map_is_running = true;
      QUIState::ui_state.scene.map_on_overlay = false;
      Params().put("OpkrMapEnable", "1", 1);
    } else {
      QProcess::execute("pkill com.mnsoft.mappyobn");
      QUIState::ui_state.scene.map_on_top = false;
      QUIState::ui_state.scene.map_on_overlay = false;
      QUIState::ui_state.scene.map_is_running = false;
      Params().put("OpkrMapEnable", "0", 1); 
    }
    return;
  }
  if (QUIState::ui_state.scene.apks_enabled && QUIState::ui_state.scene.started && QUIState::ui_state.scene.map_is_running && map_return_btn.ptInRect(e->x(), e->y())) {
    QSoundEffect effect3;
    effect3.setSource(QUrl::fromLocalFile("/data/openpilot/selfdrive/assets/sounds/warning_1.wav"));
    //effect1.setLoopCount(1);
    //effect1.setLoopCount(QSoundEffect::Infinite);
    //effect1.setVolume(0.1);
    effect3.play();
    QProcess::execute("am start --activity-task-on-home com.mnsoft.mappyobn/com.mnsoft.mappy.MainActivity");
    QUIState::ui_state.scene.map_on_top = true;
    QUIState::ui_state.scene.map_on_overlay = false;
    return;
  }
  // OPKR REC
  if (QUIState::ui_state.scene.started && !sidebar->isVisible() && !QUIState::ui_state.scene.map_on_top && !QUIState::ui_state.scene.comma_stock_ui && rec_btn.ptInRect(e->x(), e->y())) {
    QUIState::ui_state.scene.recording = !QUIState::ui_state.scene.recording;
    QUIState::ui_state.scene.touched = true;
    return;
  }
  // Laneless mode
  if (QUIState::ui_state.scene.started && !sidebar->isVisible() && !QUIState::ui_state.scene.map_on_top && QUIState::ui_state.scene.end_to_end && !QUIState::ui_state.scene.comma_stock_ui && laneless_btn.ptInRect(e->x(), e->y())) {
    QUIState::ui_state.scene.laneless_mode = QUIState::ui_state.scene.laneless_mode + 1;
    if (QUIState::ui_state.scene.laneless_mode > 2) {
      QUIState::ui_state.scene.laneless_mode = 0;
    }
    if (QUIState::ui_state.scene.laneless_mode == 0) {
      Params().put("LanelessMode", "0", 1);
    } else if (QUIState::ui_state.scene.laneless_mode == 1) {
      Params().put("LanelessMode", "1", 1);
    } else if (QUIState::ui_state.scene.laneless_mode == 2) {
      Params().put("LanelessMode", "2", 1);
    }
    return;
  }
  // Monitoring mode
  if (QUIState::ui_state.scene.started && !sidebar->isVisible() && !QUIState::ui_state.scene.map_on_top && monitoring_btn.ptInRect(e->x(), e->y())) {
    QUIState::ui_state.scene.monitoring_mode = !QUIState::ui_state.scene.monitoring_mode;
    if (QUIState::ui_state.scene.monitoring_mode) {
      Params().put("OpkrMonitoringMode", "1", 1);
    } else {
      Params().put("OpkrMonitoringMode", "0", 1);
    }
    return;
  }
  // Stock UI Toggle
  if (QUIState::ui_state.scene.started && !sidebar->isVisible() && !QUIState::ui_state.scene.map_on_top && stockui_btn.ptInRect(e->x(), e->y())) {
    QUIState::ui_state.scene.comma_stock_ui = !QUIState::ui_state.scene.comma_stock_ui;
    if (QUIState::ui_state.scene.comma_stock_ui) {
      Params().put("CommaStockUI", "1", 1);
    } else {
      Params().put("CommaStockUI", "0", 1);
    }
    return;
  }
  // Handle sidebar collapsing
  if (onroad->isVisible() && (!sidebar->isVisible() || e->x() > sidebar->width())) {

    // TODO: Handle this without exposing pointer to map widget
    // Hide map first if visible, then hide sidebar
    if (onroad->map != nullptr && onroad->map->isVisible()) {
      onroad->map->setVisible(false);
    } else if (!sidebar->isVisible()) {
      sidebar->setVisible(true);
    } else {
      sidebar->setVisible(false);

      if (onroad->map != nullptr) onroad->map->setVisible(true);
    }
    QUIState::ui_state.sidebar_view = !QUIState::ui_state.sidebar_view;
  }

  QUIState::ui_state.scene.setbtn_count = 0;
  QUIState::ui_state.scene.homebtn_count = 0;
}

// OffroadHome: the offroad home page

OffroadHome::OffroadHome(QWidget* parent) : QFrame(parent) {
  QVBoxLayout* main_layout = new QVBoxLayout(this);
  main_layout->setMargin(50);

  // top header
  QHBoxLayout* header_layout = new QHBoxLayout();

  date = new QLabel();
  header_layout->addWidget(date, 0, Qt::AlignHCenter | Qt::AlignLeft);

  alert_notification = new QPushButton();
  alert_notification->setObjectName("alert_notification");
  alert_notification->setVisible(false);
  QObject::connect(alert_notification, &QPushButton::released, this, &OffroadHome::openAlerts);
  header_layout->addWidget(alert_notification, 0, Qt::AlignHCenter | Qt::AlignRight);

  QLabel* version = new QLabel(getBrandVersion());
  header_layout->addWidget(version, 0, Qt::AlignHCenter | Qt::AlignRight);

  main_layout->addLayout(header_layout);

  // main content
  main_layout->addSpacing(25);
  center_layout = new QStackedLayout();

  QHBoxLayout* statsAndSetup = new QHBoxLayout();
  statsAndSetup->setMargin(0);

  DriveStats* drive = new DriveStats;
  drive->setFixedSize(800, 800);
  statsAndSetup->addWidget(drive);

  SetupWidget* setup = new SetupWidget;
  statsAndSetup->addWidget(setup);

  QWidget* statsAndSetupWidget = new QWidget();
  statsAndSetupWidget->setLayout(statsAndSetup);

  center_layout->addWidget(statsAndSetupWidget);

  alerts_widget = new OffroadAlert();
  QObject::connect(alerts_widget, &OffroadAlert::closeAlerts, this, &OffroadHome::closeAlerts);
  center_layout->addWidget(alerts_widget);
  center_layout->setAlignment(alerts_widget, Qt::AlignCenter);

  main_layout->addLayout(center_layout, 1);

  // set up refresh timer
  timer = new QTimer(this);
  QObject::connect(timer, &QTimer::timeout, this, &OffroadHome::refresh);
  timer->start(10 * 1000);

  setStyleSheet(R"(
    * {
     color: white;
    }
    OffroadHome {
      background-color: black;
    }
    #alert_notification {
      padding: 15px;
      padding-left: 30px;
      padding-right: 30px;
      border: 1px solid;
      border-radius: 5px;
      font-size: 40px;
      font-weight: 500;
    }
    OffroadHome>QLabel {
      font-size: 55px;
    }
  )");
}

void OffroadHome::showEvent(QShowEvent *event) {
  refresh();
}

void OffroadHome::openAlerts() {
  center_layout->setCurrentIndex(1);
}

void OffroadHome::closeAlerts() {
  center_layout->setCurrentIndex(0);
}

void OffroadHome::refresh() {
  bool first_refresh = !date->text().size();
  if (!isVisible() && !first_refresh) {
    return;
  }

  QString dayofweek = "";
  if (QDate::currentDate().dayOfWeek() == 1) {
    dayofweek = "월요일";
  } else if (QDate::currentDate().dayOfWeek() == 2) {
    dayofweek = "화요일";
  } else if (QDate::currentDate().dayOfWeek() == 3) {
    dayofweek = "수요일";
  } else if (QDate::currentDate().dayOfWeek() == 4) {
    dayofweek = "목요일";
  } else if (QDate::currentDate().dayOfWeek() == 5) {
    dayofweek = "금요일";
  } else if (QDate::currentDate().dayOfWeek() == 6) {
    dayofweek = "토요일";
  } else if (QDate::currentDate().dayOfWeek() == 7) {
    dayofweek = "일요일";
  }
  date->setText(QDateTime::currentDateTime().toString("yyyy년 M월 d일 " + dayofweek));

  // update alerts

  alerts_widget->refresh();
  if (!alerts_widget->alertCount && !alerts_widget->updateAvailable) {
    closeAlerts();
    alert_notification->setVisible(false);
    return;
  }

  if (alerts_widget->updateAvailable) {
    alert_notification->setText("업데이트");
  } else {
    int alerts = alerts_widget->alertCount;
    alert_notification->setText(QString::number(alerts) + " 경고" + (alerts == 1 ? "" : "S"));
  }

  if (!alert_notification->isVisible() && !first_refresh) {
    openAlerts();
  }
  alert_notification->setVisible(true);
  // Red background for alerts, blue for update available
  alert_notification->setStyleSheet(alerts_widget->updateAvailable ? "background-color: #364DEF" : "background-color: #E22C2C");
}
