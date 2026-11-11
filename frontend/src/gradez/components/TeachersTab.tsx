import { useState } from "react";
import { Link } from "react-router-dom";
import { courseColorProps, displayCourseName } from "../courses";
import { initials, mailtoHref, postedLabel } from "../format";
import type { CourseColorOverrides, CourseNameOverrides } from "../lib/coursePreferences";
import type { Announcement, CourseProgress } from "../types";

const POST_CAP = 5;
// Past this a post is cut short: a syllabus pasted into the stream would
// otherwise push every other teacher's post off the screen.
const LONG_POST = 320;

/** What teachers posted, and how to reach them. */
export function TeachersTab({
  announcements,
  courses,
  todayIso,
  onlyClass,
  allTo,
  courseColors,
  courseNames,
}: {
  /** Null when the posts couldn't be loaded, which is not "no posts". */
  announcements: Announcement[] | null;
  courses: CourseProgress[];
  todayIso: string;
  /** A class page's "Posts from" link asks for one class's posts. */
  onlyClass: string | null;
  allTo: string;
  courseColors: CourseColorOverrides;
  courseNames: CourseNameOverrides;
}) {
  const [shown, setShown] = useState(POST_CAP);
  const nameFor = (key: string, raw: string | null) => displayCourseName(raw ?? key, courseNames[key]);
  const posts = (announcements ?? []).filter((a) => !onlyClass || a.course_key === onlyClass);
  const older = posts.length - Math.min(shown, posts.length);
  const teachers = courses.filter((c) => c.teacher_name);
  const only = onlyClass ? courses.find((c) => c.course_key === onlyClass) : null;

  if (announcements !== null && announcements.length === 0 && teachers.length === 0) {
    return (
      <div className="gz-empty-state">
        <h2>Nothing from teachers yet</h2>
        <p>Posts and teachers appear here once Backpack Capture has sent Google Classroom.</p>
      </div>
    );
  }

  return (
    <>
      <section className="gz-section">
        <header className="gz-section-head">
          <h2>{only ? `Posted in ${nameFor(only.course_key, only.course_name)}` : "Posted lately"}</h2>
          {onlyClass && (
            <p>
              <Link to={allTo}>See every class's posts</Link>
            </p>
          )}
        </header>
        {announcements === null && <p className="gz-note">Couldn't load the posts just now.</p>}
        {announcements !== null && posts.length === 0 && <p className="gz-note">No posts yet.</p>}
        {posts.slice(0, shown).map((a) => {
          const { className, style } = courseColorProps(a.course_key, courseColors[a.course_key]);
          const who = [a.course_name || a.course_key ? nameFor(a.course_key, a.course_name) : null, a.teacher_name].filter(Boolean).join(" · ");
          return (
            <article className="gz-card gz-post" key={a.id}>
              <header>
                <span className="gz-post-who">
                  <span className={`gz-dot ${className}`} style={style} aria-hidden="true" />
                  {who}
                </span>
                <span>{postedLabel(a, todayIso)}</span>
              </header>
              <PostBody text={a.body ?? a.title} />
            </article>
          );
        })}
        {older > 0 && (
          <button type="button" className="gz-text-btn" onClick={() => setShown((s) => s + POST_CAP)}>
            Show older posts ({older})
          </button>
        )}
      </section>

      {teachers.length > 0 && !onlyClass && (
        <section className="gz-section">
          <header className="gz-section-head">
            <h2>Who teaches what</h2>
            <p>Emails come from the school's staff directory.</p>
          </header>
          <ul className="gz-card gz-list">
            {teachers.map((c) => {
              const { className, style } = courseColorProps(c.course_key, courseColors[c.course_key]);
              const name = nameFor(c.course_key, c.course_name);
              const mail = mailtoHref(c.teacher_emails, name);
              return (
                <li key={c.course_key} className="gz-teacher-row">
                  <span className={`gz-tile gz-tile-sm ${className}`} style={style} aria-hidden="true">
                    {initials(name)}
                  </span>
                  <span className="gz-row-main">
                    <span className="gz-row-title gz-is-light">{c.teacher_name}</span>
                    <span className="gz-row-sub">{name}</span>
                  </span>
                  {mail ? (
                    <a className="gz-text-btn" href={mail} aria-label={`Email ${c.teacher_name}`}>
                      Email
                    </a>
                  ) : (
                    <span className="gz-row-sub">No email on file</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}

function PostBody({ text }: { text: string }) {
  const [whole, setWhole] = useState(false);
  const long = text.length > LONG_POST;
  return (
    <>
      <p className="gz-post-body">{long && !whole ? `${text.slice(0, LONG_POST).trimEnd()}…` : text}</p>
      {long && (
        <button type="button" className="gz-text-btn" aria-expanded={whole} onClick={() => setWhole((w) => !w)}>
          {whole ? "Show less" : "Show the whole post"}
        </button>
      )}
    </>
  );
}
