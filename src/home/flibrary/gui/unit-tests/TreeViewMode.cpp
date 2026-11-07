#include <QAction>
#include <QApplication>
#include <QDir>
#include <QEventLoop>
#include <QTemporaryDir>
#include <QTimer>
#include <QToolButton>

#include <gtest/gtest.h>

#include "interface/logic/ICollectionController.h"
#include "interface/ui/IUiFactory.h"

#include "Hypodermic/Hypodermic.h"
#include "gui/TreeView.h"
#include "gui/di_ui.h"
#include "gutil/di_gutil.h"
#include "logic/di_logic.h"
#include "settings/Settings.h"

using namespace HomeCompa;
using namespace Flibrary;

namespace {

// The test's settings and collection, removed when the test program ends
QString Root()
{
	static const QTemporaryDir root;
	return root.path();
}

// The app's container, with the settings in a file of the test's folder: on Windows and macOS the app's own settings
// live in the registry and in a plist, where the test must not touch them
std::shared_ptr<Hypodermic::Container> BuildContainer(std::shared_ptr<Hypodermic::Container>& container)
{
	Hypodermic::ContainerBuilder builder;
	DiLogic(builder, container);
	DiUi(builder, container);
	Util::DiGUtil(builder, container);
	builder
		.registerInstanceFactory([](Hypodermic::ComponentContext&) -> std::shared_ptr<SettingsFactory::AbstractSettings> {
			return SettingsFactory::Create(QDir(Root()).filePath("settings.ini"));
		})
		.as<ISettings>()
		.singleInstance();
	return container = builder.build();
}

class ActiveCollectionWaiter final : public ICollectionsObserver
{
public:
	explicit ActiveCollectionWaiter(QEventLoop& eventLoop)
		: m_eventLoop { eventLoop }
	{
	}

private: // ICollectionsObserver
	void OnActiveCollectionChanged() override
	{
		m_eventLoop.exit(0);
	}

	void OnNewCollectionCreating(bool) override
	{
	}

private:
	QEventLoop& m_eventLoop;
};

// TreeView creates its mode actions only for an active collection; an empty folder makes an empty one
bool CreateEmptyCollection()
{
	const auto folder = QDir(Root()).filePath("library");
	if (!QDir().mkpath(folder))
		return false;

	std::shared_ptr<Hypodermic::Container> container;
	const auto                             controller = BuildContainer(container)->resolve<ICollectionController>();

	QEventLoop             eventLoop;
	ActiveCollectionWaiter waiter(eventLoop);
	controller->RegisterObserver(&waiter);
	controller->CreateCollection(*controller->CreateCollection("Empty", folder + ".db", folder, {}, {}));
	QTimer dialogCloser; // the app reports the new collection in a message box
	dialogCloser.callOnTimeout([] {
		if (auto* dialog = QApplication::activeModalWidget())
			dialog->close();
	});
	dialogCloser.start(std::chrono::milliseconds(100));
	QTimer::singleShot(std::chrono::seconds(30), &eventLoop, [&] {
		eventLoop.exit(1);
	});
	const auto created = eventLoop.exec() == 0;
	controller->UnregisterObserver(&waiter);
	return created;
}

// The books view switches between its two modes (list and tree) with the same TreeView code as the navigation view's
// mode menu, and it shows them for an empty collection too
TEST(TreeView, ChosenModeBecomesCheckedAndDisabled)
{
	ASSERT_TRUE(CreateEmptyCollection());

	std::shared_ptr<Hypodermic::Container> container;
	const auto                             view    = BuildContainer(container)->resolve<IUiFactory>()->CreateTreeViewWidget(ItemType::Books);
	const auto                             actions = view->findChild<QToolButton*>("btnMode")->actions();
	ASSERT_EQ(actions.size(), 2);

	auto* current = actions[0]->isChecked() ? actions[0] : actions[1];
	auto* other   = current == actions[0] ? actions[1] : actions[0];
	ASSERT_TRUE(current->isChecked());
	ASSERT_FALSE(current->isEnabled());

	other->trigger();

	EXPECT_TRUE(other->isChecked());
	EXPECT_FALSE(other->isEnabled());
	EXPECT_FALSE(current->isChecked());
	EXPECT_TRUE(current->isEnabled());
}

} // namespace
